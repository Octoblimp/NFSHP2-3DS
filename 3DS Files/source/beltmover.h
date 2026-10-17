// beltmover -- BeltMover, the cheap mover of an AI car no player is near:
// retail's BeltMover.obj, 0x00204098 to 0x002056b4.
//
// The car rides a belt. SetBelt resamples the driver's DriveTarget and
// makes its points the control points of a QuickSpline; FindCoordinates
// finds where on it the car is (the parameter `v`), how fast the parameter
// moves (`dv`, the car's speed in control points a second) and how fast
// that should change (`ddv`, towards 0.899 of the speed the driver wants,
// no faster than CalculateMaxAcceleration allows). Move then advances the
// parameter as a quadratic in the belt's own clock, fTime, and puts the
// car on the curve: the heading eased towards the tangent half a second on
// by one tCubic2D, the car slid out of the bend by another and moved across
// the belt by a tCubic1D, with an Average of the sideways acceleration
// deciding how far it slides and whether it is sliding. Nothing is
// integrated: the CarState is written outright, the four Wheels are placed
// for drawing and skids, and the car's controller is told when the belt
// leaves the ground under it.
//
// AICarController::Think puts a car on the belt (Car::SetMovementMode's
// BELT_MOVEMENT arm builds one through carmodes.h's gBeltMoverCtorFn) and
// calls SetBelt each think it keeps it there (gBeltMoverSetBeltFn);
// CalculateMaxAcceleration asks the belt for its slope
// (nearbycar.h's gBeltMoverGravityFn). main.c points the three at this.
//
// Everything is here, DoSnapshot (0x00204468) the replay's since TASKS 72c.
// ClearCalculatedVariables (0x00204460) and DebugScreenPrint (0x002053a0)
// are `jr ra`; the first is kept because the constructor and DoSnapshot
// call it.
//
// See docs/formats/belt-mover.md.

#ifndef BELTMOVER_H
#define BELTMOVER_H

#include <stddef.h>
#include <stdint.h>

#include "average.h"
#include "banim.h"         // BSpline (tCubic1D), BSpline2D (tCubic2D)
#include "bvector.h"
#include "car.h"
#include "graph.h"
#include "physicscar.h"    // CarMover
#include "quickspline.h"
#include "wheel.h"

// 72 bytes on the console, the mdebug record's names. CarMover's eight,
// then the car and the belt.
typedef struct BeltMover {
    CarMover     Mover;         //  0  Driver 0, vptr 4
    Car         *pCar;          //  8
    float        fTime;         // 12  seconds since FindCoordinates
    float        fScale;        // 16  control points a metre
    QuickSpline *pSpline;       // 20  EXTRAPOLATED, 20 points
    BSpline     *pCubicU;       // 24  across the belt
    float        v;             // 28  the parameter at fTime 0
    float        dv;            // 32  ... its rate
    float        ddv;           // 36  ... and half its acceleration
    BSpline2D   *pCubicAng;     // 40  the heading, eased
    BSpline2D   *pCubicSlide;   // 44  the slide out of a bend
    Average     *pAvgAccel;     // 48  30 samples of sideways acceleration
    int32_t      bSliding;      // 52
    Wheel       *pWheels[4];    // 56
} BeltMover;                    // 72

#ifndef BELTMOVER_NO_ASSERT
typedef char beltmover_layout_check[
    (sizeof(void *) != 4
     || (offsetof(BeltMover, pCar) == 8
         && offsetof(BeltMover, fTime) == 12
         && offsetof(BeltMover, pSpline) == 20
         && offsetof(BeltMover, pCubicU) == 24
         && offsetof(BeltMover, v) == 28
         && offsetof(BeltMover, ddv) == 36
         && offsetof(BeltMover, pCubicAng) == 40
         && offsetof(BeltMover, pAvgAccel) == 48
         && offsetof(BeltMover, bSliding) == 52
         && offsetof(BeltMover, pWheels) == 56
         && sizeof(BeltMover) == 72)) ? 1 : -1];
typedef char beltmover_cubic_check[
    (sizeof(BSpline) == 48 && sizeof(BSpline2D) == 96) ? 1 : -1];
#endif

// _vt$9BeltMover, 0x002bb090, CarMover's layout: the destructor
// (0x002043a0), Move (0x00204d78) and DoSnapshot (0x00204468).
#define BELTMOVER_VTABLE     0x002bb090u
#define BELTMOVER_VT_ENTRIES 4

// The name every one of the constructor's bMallocs passes, with its line
// as the third argument: the string at 0x002bb048.
#define BELTMOVER_FILE "..\\indep\\src\\beltmover.cpp"

// The two Graphs SlideCoef reads, gp-16592 and gp-16584, which
// _GLOBAL_$I$fBeltAccelCoef (0x002055c8) builds over the four points at
// 0x0031b9d0 and at 0x0031b9f0. The port has them as data. SlideCoef
// rewrites points 1 to 3's x each call, so the points are not const.
extern Graph BeltSlideGraph;          // gp-16592  not sliding
extern Graph BeltSlidingGraph;        // gp-16584  sliding

// 0x00204098, `__9BeltMoverP3Car`. Every word but the Driver, which
// SetMovementMode's tail stores; then from the file's bMallocs (pool 16)
// an Average of 30, a QuickSpline (EXTRAPOLATED, OVERHAUSER, 20), the
// tCubic1D and the two tCubic2Ds, each cubic still at 0 with flags 1 and a
// duration and threshold of 1. The heading's cubic starts at the car's
// velocity along its heading, and its rate at the speed times
// AngularVelocity.z times 0.4 along the heading turned a quarter left; the
// slide's two durations are 0.3. Then the four Wheels, from Wheel's pool,
// on the type's WheelInfos, its front or rear TireInfo, its ControlInfo
// and the car's CarState, and ClearCalculatedVariables.
BeltMover *beltmover_init(BeltMover *m, Car *car);

// carmodes.h's CarMoverCtorFn: the constructor on memory Car allocated.
CarMover *beltmover_construct(void *mem, Car *car);

// 0x002043a0. Its own vptr; the Average and the QuickSpline through their
// destructors (flags 3) when set; the three cubics through
// __builtin_delete, unchecked; each Wheel set through its own table's
// destructor (flags 3); then ~CarMover with this call's flags.
void beltmover_destroy(BeltMover *m, int32_t flags);

// 0x00204460, `jr ra`.
void beltmover_clear_calculated_variables(BeltMover *m);

// 0x002045b8. `a` is the belt's point at `t` less `pos` and `b` its
// tangent there, all four lanes; the answer is their dot product, xyz.
float beltmover_dot(BeltMover *m, const bVector3 *pos, bVector3 *a,
                    bVector3 *b, float t);

// 0x00204668. 0 with no control points; else -9.8 times the z of the unit
// tangent at `v`: what the slope takes off the car's acceleration.
float beltmover_get_acceleration_due_to_gravity(BeltMover *m);

// 0x002046f0. CalculateMaxAcceleration at dv over fScale, the car's speed.
float beltmover_get_maximum_acceleration(BeltMover *m);

// 0x00204718. fTime to 0 and fScale from the driver's DriveTarget; the
// closest parameter to the car, from the closest control point; dv from
// the car's speed; ddv from the desired speed and time to it, clamped to
// the most the car can do and to -20 m/s/s; the across-belt cubic to the
// car's offset and sideways speed, its duration 0.5; the heading's
// durations 0.4.
void beltmover_find_coordinates(BeltMover *m);

// 0x00204990. The across-belt cubic's flags cleared; the driver's
// DriveTarget resampled; its points copied into the spline, w 0, the
// spline marked dirty after each; then FindCoordinates.
void beltmover_set_belt(BeltMover *m);

// 0x00204a30. Whether the car slides at `accel` (the Average's sideways
// acceleration): its sign times the Graph's value at the force it needs,
// the Graph's breakpoints moved to the grip it has. Starting to slide sets
// the slide cubic's durations to 1; stopping sets them to 0.3 and its rate
// 1.6 times.
float beltmover_slide_coef(BeltMover *m, float accel);

// 0x00204bd8. How far the belt drops away under the car over the next `dt`
// seconds, in nine steps a tenth of `dt` apart: the car thrown from each
// point the belt is below it, the gaps summed, times 0.1.
float beltmover_average_air(BeltMover *m, float dt);

// 0x00204d78. One frame on the belt; see docs/formats/belt-mover.md.
float beltmover_move(BeltMover *m, float dt);

// 0x002053a8 / 0x00205458 / 0x002054d8. The belt's point, velocity and
// acceleration `t` seconds after FindCoordinates: the parameter is
// v + t(dv + t ddv). GetPoint keeps a point before the start no lower than
// the first control point. Each returns `out`.
bVector3 *beltmover_get_point(BeltMover *m, bVector3 *out, float t);
bVector3 *beltmover_get_derivative(BeltMover *m, bVector3 *out, float t);
bVector3 *beltmover_get_second_derivative(BeltMover *m, bVector3 *out,
                                          float t);

// 0x00204468, slot 24, a "BeltMover" section: CarMover's (nothing), v, dv,
// ddv, fTime, fScale, bSliding, the three cubics' raw 48, 96 and 96 bytes,
// the spline at three floats a point, the Average and the four Wheels;
// ClearCalculatedVariables when taking or restoring.
struct ReplaySnapshot;
void beltmover_do_snapshot(BeltMover *m, struct ReplaySnapshot *s);

// Installs the table. The game calls it once at boot; a harness calls it
// after vt_reset().
void beltmover_install_vtables(void);

// Points carmodes.h's gBeltMoverCtorFn and gBeltMoverSetBeltFn and
// nearbycar.h's gBeltMoverGravityFn at this file.
void beltmover_install_seams(void);

#endif
