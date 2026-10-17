// nearbycar -- what an AI car knows of the cars around it, and where it is
// driving: NearbyCarList (0x001937e0 .. 0x00193e20, 0x001940c8),
// DrivingInformation (Clear, 0x00193e68), and five free functions of the
// AI's that read them:
//
//   CalculateMaxAcceleration           0x001cce50  (the demo's 0x001c2cb0)
//   CanICatchThisCar                   0x001ccfd8  (0x001c2e38)
//   DoWeCareAboutThisCar               0x001ccde8  (0x001c2c48)
//   GetCurrentCurvatureOfDrivingLine   0x001ccbc0  (0x001c2a20)
//   HighlightDrivingLine               0x001cb450  (0x001c1310)
//
// The AI's Think builds the list each frame: every car on the world's
// CarList that is not poofed and is drawn, near enough by the look-ahead
// or catchable, and near enough round the track, up to 16 of them -- the
// car itself among them, at its own origin. Each is in the car's own
// space, sorted ahead first.
//
// Not here, as nothing in retail calls them: NearbyCar's operator=
// (0x001937b0; the copies are bMemCpy), and the free
// GetLateralOffsetFromCarInDrivingLineSpace (0x001cd5c8). The DoSnapshots
// (0x001937e0, 0x00193ea0) are the replay's, since TASKS 72c.
//
// Checked against retail by tools/nearbycar_check.py. Written up in
// docs/formats/ai-driving-info.md.
#ifndef NEARBYCAR_H
#define NEARBYCAR_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "car.h"
#include "drivingchoice.h"
#include "drivinglocation.h"

// 28 bytes, type#1305. Position and Velocity are in the list's car's space:
// the other car's place, and its velocity less the car's, turned to the
// car's heading. The two half sizes are the other car's, seen along the
// car's axes.
typedef struct NearbyCar {
    bVector2 Position;           //  0
    bVector2 Velocity;           //  8
    float    ApparentHalfSizeL;  // 16
    float    ApparentHalfSizeD;  // 20
    Car     *TheCar;             // 24
} NearbyCar;                     // 28

#define NEARBYCARLIST_MAX 16

// 464 bytes, type#1312.
typedef struct NearbyCarList {
    Car      *MyCar;                        //   0
    int32_t   NumCarsInArray;               //   4
    NearbyCar Array[NEARBYCARLIST_MAX];     //   8
    float     MyHalfSizeL;                  // 456
    float     MyHalfSizeD;                  // 460
} NearbyCarList;                            // 464

// 492 bytes, type#1328.
typedef struct DrivingInformation {
    NearbyCarList   MyNearbyCarList;        //   0
    DrivingLocation MyDrivingLocation;      // 464
    DrivingChoice   MyDrivingChoice;        // 480
} DrivingInformation;                       // 492

// The record's pointer at its end, and the list's at its start, are the
// only pointers that move anything on a 64-bit host, each by its widening.
#define NEARBYCAR_SLACK ((size_t)(sizeof(void *) - 4))

#ifndef NEARBYCAR_NO_ASSERT
typedef char nearbycar_layout_check[
    (offsetof(NearbyCar, Velocity) == 8
     && offsetof(NearbyCar, ApparentHalfSizeL) == 16
     && offsetof(NearbyCar, ApparentHalfSizeD) == 20
     && offsetof(NearbyCar, TheCar) == 24
     && sizeof(NearbyCar) == 28 + NEARBYCAR_SLACK
     && offsetof(NearbyCarList, NumCarsInArray) == 4 + NEARBYCAR_SLACK
     && offsetof(NearbyCarList, Array) == 8 + 2 * NEARBYCAR_SLACK
     && offsetof(NearbyCarList, MyHalfSizeL)
        == 456 + 18 * NEARBYCAR_SLACK
     && offsetof(NearbyCarList, MyHalfSizeD)
        == 460 + 18 * NEARBYCAR_SLACK) ? 1 : -1];
#endif

// TrafficDriverLookaheadFactor (gp-20496, 0x003308e0): a traffic car looks
// three times as far ahead for cars.
extern float TrafficDriverLookaheadFactor;          // 3.0f

// AIActionPassMaxTimeAheadToMakeAttempt (gp-18164, 0x003311fc): how far
// ahead in time CanICatchThisCar looks.
extern float AIActionPassMaxTimeAheadToMakeAttempt; // 3.0f

// HighlightDrivingLine's two (gp-18316 and gp-18312, -1 at boot), which
// only the route debug drawing reads.
extern int32_t HighlightDrivingLineInRouteNumber;
extern int32_t HighlightDrivingLineNumber;

// ---------------------------------------------------------- NearbyCarList

// 0x00193898. Nothing at all without a car or a location (the location is
// not otherwise read, nor is `unused`). Otherwise the array is zeroed and
// built afresh from pCurrentWorld's CarList, as the header says; a car is
// kept when it is within the look-ahead (CalculateLookAheadDistance, three
// times as far for a traffic car) in the car's space or CanICatchThisCar
// says so, and within three look-aheads round the track
// (CompareDistances). A car tried and not kept leaves its Position,
// Velocity and TheCar in the next free entry. The kept ones are bubble
// sorted by Position.y, the greatest first, in a copy on the stack, then
// copied back, and MyHalfSizeL and MyHalfSizeD are the car's bounding
// box's y and x maxima.
void nearbycarlist_build_array(NearbyCarList *l, DrivingLocation *loc,
                               float unused);

// 0x001940c8. No cars, and both half sizes 0. The array is left as it is.
void nearbycarlist_clear_array(NearbyCarList *l);

// 0x00193d90. The first entry whose TheCar is `c`, among the first
// NumCarsInArray, or -1.
int32_t nearbycarlist_get_cars_index_in_array(const NearbyCarList *l,
                                              const Car *c);

// 0x00193dd8. `c`'s entry, or NULL.
NearbyCar *nearbycarlist_get_nearby_car(NearbyCarList *l, const Car *c);

// 0x00193e20. The entry before `c`'s, which is the car just ahead of it,
// or NULL when `c` is first or not there.
NearbyCar *nearbycarlist_get_car_ahead(NearbyCarList *l, const Car *c);

// ------------------------------------------------------ DrivingInformation

// 0x00193e68. The list's ClearArray, the location's Clear and the choice's
// three words 0, inline.
void drivinginformation_clear(DrivingInformation *d);

// The replay's (TASKS 72c).
//
// 0x001937e0, a "NearbyCarList" section: NumCarsInArray as one signed
// byte, MyHalfSizeD, MyHalfSizeL, then that many 28-byte records as they
// are, TheCar's raw pointer and all. Nothing in retail calls it.
//
// 0x00193ea0, no section: taking or restoring zeroes the list's count and
// half sizes first, then the location and the choice. The list itself is
// not saved; the AI rebuilds it every Think.
struct ReplaySnapshot;
void nearbycarlist_do_snapshot(NearbyCarList *l, struct ReplaySnapshot *s);
void drivinginformation_do_snapshot(DrivingInformation *d,
                                    struct ReplaySnapshot *s);

// ---------------------------------------------------- the free functions

// CalculateMaxAcceleration reaches BeltMover's
// GetAccelerationDueToGravity (0x00204668) through this, which main.c
// points at beltmover.c's: nearbycar.c sits below the mover in the link.
typedef float (*BeltMoverGravityFn)(CarMover *m);
extern BeltMoverGravityFn gBeltMoverGravityFn;

// 0x001cce50. The most the car could accelerate at `speed`:
//
//   v     = speed / State.BoostFactor
//   accel = the car type's acceleration table at v
//   drag  = ((1 - DraftFactor) * Aero.Drag) * (v * v)
//   accel = min(accel, drag) when v is at least Control.SpeedLimiter * 0.447
//   grade = -9.8 * the body's x axis' z, normalised; the belt mover's
//           when in BELT_MOVEMENT
//   max   = (accel * 1.0 - drag / Body.Mass) + grade
float ai_calculate_max_acceleration(Car *car, float speed);

// 0x001ccf78. The most the car could decelerate at `speed`, negative: the
// tyres' grip under the car's weight and its downforce, over its mass.
//
//   down  = (Aero.FrontDownforce + Aero.RearDownforce) * 0.5
//   mu    = (Tires[1] + Tires[0]).StaticFrictionCoefficient * 0.5
//   max   = -(((|speed| * down + 9.8 * Body.Mass) * mu) / Body.Mass)
float ai_calculate_max_deceleration(Car *car, float speed);

// 0x001ccfd8. Whether `car` could reach `nc` within
// AIActionPassMaxTimeAheadToMakeAttempt seconds: the distance below the
// closing speed's run plus half the difference in forward accelerations
// (the sum when the two face apart) run over the time squared. `maxAccel`
// and `flag` change nothing.
int ai_can_i_catch_this_car(NearbyCar *nc, Car *car, float maxAccel,
                            int flag);

// 0x001ccde8. A nearby car that is not the list's own, and whose rear is
// ahead of the car's front: Position.y above -(ApparentHalfSizeD +
// MyHalfSizeD), half a metre less when it is a player's.
int ai_do_we_care_about_this_car(const NearbyCar *nc,
                                 const NearbyCarList *l);

// 0x001ccbc0. The bend in the location's line over the next 12 points:
// the length of the cross product of the two six-point chords, each
// normalised, negated when the product's z is 0 or more (so a straight
// line is -0). 0 when the location is clear or the route has fewer than
// 13 points from here.
float ai_get_current_curvature_of_driving_line(DrivingLocation *loc);

// 0x001cb450. When `carIndex` is CameraFollowThisCarInstead, the
// location's route number and line into the two globals above, for the
// route debug drawing.
void ai_highlight_driving_line(DrivingLocation *loc, int32_t carIndex);

#endif /* NEARBYCAR_H */
