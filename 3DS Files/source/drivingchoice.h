// drivingchoice -- DrivingChoice, which way round the traffic an AI car
// has chosen to go: one of the four driving lines, or one side of a car.
// Retail's DrivingChoice.hpp; DrivingChoice.obj is 0x00241b88 ..
// 0x00245600. With it, the walk along the route that turns a choice into
// a DriveTarget: the FuturePoint list, AdvancePoint and
// GetRoutePointsToUse, which the demo named and retail keeps unnamed.
//
// Here so far (step 11b-2): the small methods, the room and the side
// tests, and FillUpDriveTarget with everything under it. Still to come:
// BuildDriveTargetAroundCar and DoSmoothOffsetChange (11b-3), then
// IsDriveable, TryChoice, TryToDriveAroundCar and MakeNewChoice (11b-4).
// DoSnapshot (0x00241b88) is the replay's, and GetTextDescription
// (0x00241c38) a debug string.
//
// Checked against retail by tools/drivingchoice_check.py. Written up in
// docs/formats/ai-driving-choice.md.
#ifndef DRIVINGCHOICE_H
#define DRIVINGCHOICE_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"

struct AICarController;
struct DriveTarget;
struct DrivingLocation;
struct NearbyCar;
struct NearbyCarList;
struct Signpost;
struct TrackRoute;
struct TrackRoutePoint;

// 17DrivingChoiceType, type#1063, from the .mdebug.
typedef int32_t DrivingChoiceType;
#define CHOICE_NONE               ((DrivingChoiceType)0)
#define CHOICE_DRIVING_LINE_0     ((DrivingChoiceType)1)
#define CHOICE_DRIVING_LINE_1     ((DrivingChoiceType)2)
#define CHOICE_DRIVING_LINE_2     ((DrivingChoiceType)3)
#define CHOICE_DRIVING_LINE_3     ((DrivingChoiceType)4)
#define CHOICE_LEFT_SIDE_OF_CAR   ((DrivingChoiceType)5)
#define CHOICE_RIGHT_SIDE_OF_CAR  ((DrivingChoiceType)6)
#define NUM_DRIVING_CHOICE_TYPES  7

// 25MovementWithRespectToLine, type#1052.
typedef int32_t MovementWithRespectToLine;
#define MOVEMENT_TOWARDS_LINE                ((MovementWithRespectToLine)0)
#define MOVEMENT_PARALLEL_TO_LINE            ((MovementWithRespectToLine)1)
#define MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK  ((MovementWithRespectToLine)2)
#define MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK ((MovementWithRespectToLine)3)
#define MOVEMENT_NONE                        ((MovementWithRespectToLine)4)

// 12 bytes, type#1071.
typedef struct DrivingChoice {
    DrivingChoiceType Type;                     // 0
    Car              *pCar;                     // 4
    int32_t           UseExtraLateralDistance;  // 8, a bool
} DrivingChoice;                                // 12

#ifndef DRIVINGCHOICE_NO_ASSERT
typedef char drivingchoice_layout_check[
    (offsetof(DrivingChoice, pCar) == sizeof(void *)
     && offsetof(DrivingChoice, UseExtraLateralDistance) == 2 * sizeof(void *)
     && sizeof(DrivingChoice) == 3 * sizeof(void *)) ? 1 : -1];
#endif

// A point on the route ahead, as the walk finds it: 20 bytes, type#1095.
// The offset is the lateral one to add to the line's there, which a
// crossed signpost sets so the car does not jump across to the new
// route's line.
typedef struct FuturePoint {
    int32_t nRouteNumber;      //  0
    int32_t nPointNumber;      //  4
    int32_t nLine;             //  8
    float   fOffset;           // 12
    int32_t bCrossedSignpost;  // 16, a bool
} FuturePoint;                 // 20

#define FUTUREPOINTLIST_MAX 20

// A count and twenty points, on the stack of whoever walks: 404 bytes.
// The constructor zeroes the count (0x001cad30, and again at 0x00245410)
// and the destructor does nothing. Add has no bound: its callers stop at
// twenty.
typedef struct FuturePointList {
    int32_t     NumPoints;                        // 0
    FuturePoint Points[FUTUREPOINTLIST_MAX];      // 4
} FuturePointList;                                // 404

// While AICarController is not ported (step 11e), AdvancePoint asks its
// SignPostDecision (0x00191de0) through this: whether to take the sign
// onto its new route, and the line to drive there, through `line`. The
// last argument is the controller's CurrentDrivingLocation. NULL takes no
// sign.
typedef int (*AISignPostDecisionFn)(struct AICarController *c,
                                    struct Signpost *s, int32_t *line,
                                    struct DrivingLocation *loc);
extern AISignPostDecisionFn gAISignPostDecisionFn;

// ------------------------------------------------- the small methods

// 0x00245328. `type - 1 < 4`, unsigned.
static inline int drivingchoice_type_is_driving_line(DrivingChoiceType t)
{
    return (uint32_t)(t - 1) < 4u;
}

// 0x00245318. `type - 5 < 2`, unsigned.
static inline int drivingchoice_type_is_side_of_car(DrivingChoiceType t)
{
    return (uint32_t)(t - 5) < 2u;
}

// 0x00241c00. Line 0, 2, 4 .. is DRIVING_LINE_0 and 1, 3 .. is
// DRIVING_LINE_1: `line % 2 + 1`, a signed remainder, so line -1 is
// CHOICE_NONE.
DrivingChoiceType drivingchoice_get_choice_type(int32_t line);

// 0x00241c20. The route's line for a line choice: the car type's CarClass
// (a signed byte) times two, plus `type - 1`.
int32_t drivingchoice_get_driving_line(DrivingChoiceType type, Car *car);

// 0x00241cf8. Stores all three only when they agree: a line with no car,
// or a side with one. Anything else leaves the choice as it was.
void drivingchoice_set_choice(DrivingChoice *d, DrivingChoiceType type,
                              Car *car, int extra);

// 0x001cacc8 (and an uncalled copy at 0x00245338). The location's line's
// choice type, with no car.
void drivingchoice_set_choice_location(DrivingChoice *d,
                                       const struct DrivingLocation *loc);

// 0x00245370. The other's three, through the three accessors and
// SetChoice's test.
void drivingchoice_set_choice_choice(DrivingChoice *d,
                                     const DrivingChoice *other);

// 0x002453e0. All three words 0.
void drivingchoice_clear(DrivingChoice *d);

// 0x00241d40. A line: the location is not clear, its route number is
// under 50 and that route's line (GetDrivingLine with the list's car) is
// valid or fake; or the route number is 50 to 69 and the choice is
// DRIVING_LINE_0. A side: the car is in the list. Nothing else.
int drivingchoice_is_valid(const DrivingChoice *d,
                           const struct DrivingLocation *loc,
                           struct NearbyCarList *list);

// 0x00241e30. The same type, and for a side the same car.
int drivingchoice_is_equal_to(const DrivingChoice *d,
                              const DrivingChoice *other);

// 0x00242b08. A line always has room, and a NONE never. A side has room
// when its car is not off the road (GetAmountOutOfBounds below -0.001
// means on it) or when there is room on that side of it within the
// road's width at its route point: both cars' half lengths and 5 m.
int drivingchoice_is_enough_room(const DrivingChoice *d, struct NearbyCar *nc,
                                 struct NearbyCarList *list);

// 0x00243160. Sets `car`'s controller's CarToExcludeFromCollisionPrediction:
// NULL for a line, or for a side when `check` is 0. For a side with
// `check`, the choice's car is kept out of the prediction unless a traffic
// car is coming the other way and has chosen the mirror side of `car`, or
// is pulling over to the right while this goes left, or there is not
// enough room. A NONE writes nothing.
void drivingchoice_fixup_car_to_exclude_from_collision_prediction(
    const DrivingChoice *d, Car *car, int check, struct NearbyCarList *list);

// 0x002432e8. 1 for the left side of `nc`'s car, 0 for the right. A
// traffic car close to the line is passed on the right; with both cars
// near the line, far apart and the line bending (curvature 0.12 or
// more), on the inside; otherwise on the side away from the other car's
// offset. The answer flips when that side has no room.
int drivingchoice_get_preferred_side_of_car(struct NearbyCar *nc,
                                            struct NearbyCarList *list,
                                            struct DrivingLocation *loc);

// ------------------------------------------- the walk along the route

// 0x00244768. Appends one point, unbounded.
void futurepointlist_add(FuturePointList *l, int32_t route, int32_t point,
                         int32_t line, float offset, int crossed);

// 0x00244588. One point on. A point with a sign asks the controller
// first, and a sign taken moves the walk onto the new route at its
// point, with the offset that keeps the car where it was laterally, and
// sets `crossed`. Otherwise the next point on the route, with no offset,
// or 0 at the route's end.
int drivingchoice_advance_point(struct TrackRoute **route,
                                struct TrackRoutePoint **point,
                                int32_t *pointNumber, float *offset,
                                int *crossed, int32_t *line,
                                struct AICarController *ctrl);

// 0x002447c0. The points to drive past the target's last one: from the
// location, or from 10 m past the target's last point, up to the
// look-ahead and at least five, at most twenty. `*currentL` is where the
// target ends, across the line.
void drivingchoice_get_route_points_to_use(FuturePointList *l,
                                           struct DriveTarget *t,
                                           struct DrivingLocation *loc,
                                           struct NearbyCarList *list,
                                           float *currentL);

// 0x00244c88. The location's points up to `end`, on its line, at most
// twenty. AIActionAvoidRoadBlock's.
void drivingchoice_get_route_points_up_to(FuturePointList *l,
                                          struct DrivingLocation *loc,
                                          struct TrackRoutePoint *end);

// 0x002438b0. How fast, in metres a point, the car comes back to its
// line: 0 parallel to it, in the start's grace period or at 60 mph or
// less; 0.5 towards a side of the track, for a traffic car, or above
// 66 mph; 0.25 in between and in a relaxed switch.
float drivingchoice_get_speed_back_to_line(struct NearbyCarList *list,
                                           struct DrivingLocation *loc,
                                           MovementWithRespectToLine m);

// 0x00243988. Moves `*l` towards the line by `amount`, or across the road
// for the two movements towards a side, then keeps it on the road at
// `point`: within the widths, less a metre and `halfWidth` with `inside`.
void drivingchoice_reduce_current_l(float *l, MovementWithRespectToLine m,
                                    struct TrackRoutePoint *point,
                                    int32_t line, float amount,
                                    float halfWidth, int inside);

// 0x002437e8. The point's position at `l` off its line, into the target.
void drivingchoice_add_to_drive_target(float l, struct DrivingLocation *loc,
                                       FuturePoint *p,
                                       struct DriveTarget *t);

// 0x00243568. Fills the target with the route ahead, coming back to the
// line at GetSpeedBackToLine's pace, and clears the car's
// CarToExcludeFromCollisionPrediction.
void drivingchoice_fill_up_drive_target(struct DriveTarget *t,
                                        struct DrivingLocation *loc,
                                        struct NearbyCarList *list,
                                        MovementWithRespectToLine m,
                                        int inside);

#endif /* DRIVINGCHOICE_H */
