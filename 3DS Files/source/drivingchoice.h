// drivingchoice -- DrivingChoice, which way round the traffic an AI car
// has chosen to go: one of the four driving lines, or one side of a car.
// Retail's DrivingChoice.hpp; DrivingChoice.obj is 0x00241b88 ..
// 0x00245600. With it, the walk along the route that turns a choice into
// a DriveTarget: the FuturePoint list, AdvancePoint and
// GetRoutePointsToUse, which the demo named and retail keeps unnamed.
//
// Here (steps 11b-2 to 11b-4b): the small methods, the room and the side
// tests, FillUpDriveTarget with everything under it, BuildDriveTarget
// with the way round a car under it, and the choosing: IsDriveable,
// TryChoice, MakeNewChoice and TryToDriveAroundCar; and DoSnapshot
// (0x00241b88), the replay's, since TASKS 72c. Left out:
// GetTextDescription (0x00241c38), a debug string.
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

// AdvancePoint asks the controller's SignPostDecision (0x00191de0) through
// this: whether to take the sign onto its new route, and the line to drive
// there, through `line`. The last argument is the controller's
// CurrentDrivingLocation. main.c points it at
// aicarcontroller_sign_post_decision (step 11e-2); drivingchoice_check
// keeps its own stand-in here. NULL takes no sign.
typedef int (*AISignPostDecisionFn)(struct AICarController *c,
                                    struct Signpost *s, int32_t *line,
                                    struct DrivingLocation *loc);
extern AISignPostDecisionFn gAISignPostDecisionFn;

// Retail's, in DrivingChoice.obj's .sdata around WilliamsAITuningMode
// (gp-15128). The demo has none of the three and retail is stripped, so
// the names are the port's.
//
// AITrafficTuningMode (gp-15152, 0x00331dc0) is 0 and nothing in the image
// writes it. Set, a traffic car passes on the other side of a car
// (BuildDriveTargetAroundCar), drives round only racers and players
// (TryChoice) and scales its collision prediction by 1000
// (CarCollisionPredict::WillIHitThisCar).
//
// The two speeds (gp-15120 and gp-15116) are the most a car may do and
// still be passed with 6 m to spare: 20 m/s for most, 10 for traffic.
// AIActionGetUnstuck::AreWeStuckBehindSomeone reads the first too.
extern int32_t AITrafficTuningMode;   // 0
extern float   AISlowCarSpeed;        // 20.0f
extern float   AISlowTrafficSpeed;    // 10.0f

// The demo's names for two more. Above
// TryToDriveAroundCarMinSpeedForDrivingLine (gp-15136, 0x00331dd0), either
// car's speed lets TryToDriveAroundCar try the driving lines, and its
// sides without the room test;
// AIActionPass::SideOfCarIsOkay reads it too. The demo read it against
// the speed at Car 960, its VelocityMagnitude; retail's is at 964, the
// same field.
//
// AICarControllerNumDrivingLinesToConsider (gp-20136, 0x00330a48) is 1,
// and nothing writes it: the driving lines tried are DRIVING_LINE_0 to
// this less one. AICarController::GetNewDrivingLine reads it too.
extern float   TryToDriveAroundCarMinSpeedForDrivingLine;  // 20.0f
extern int32_t AICarControllerNumDrivingLinesToConsider;   // 1

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

// ---------------------------------------- the target, and round a car

// 0x00244d80, new in retail. The index of the list's point nearest `pos`
// of those ahead of it, from `start` (a negative start is 0), or -1.
// Past a point d metres away it skips d / 24 - 2 more.
int32_t futurepointlist_find_closest_point_ahead(const FuturePointList *l,
                                                 const bVector2 *pos,
                                                 int32_t start);

// 0x00244ea0. Retail's takes the list where the demo's took a route and
// its points. Adds the list's points 0 to `index` - 2, `l` moving from
// `fromL` to `toL` off each one's line in step with the distance along
// the lines from point 0, and kept on the road (within a metre and the
// car's half width with `inside`). Nothing below index 3.
void drivingchoice_do_smooth_offset_change(FuturePointList *l,
                                           struct DriveTarget *t,
                                           struct NearbyCarList *list,
                                           int32_t index, float fromL,
                                           float toL, int inside);

// 0x002442c0, new in retail. The room to leave between the two cars'
// sides: how far apart they are across their lines now, measured at the
// list's point 0 and at `index` (-1 asks the search), less both half
// widths; and no less than 2 m, or 1.5 beside a player, or 6 beside a car
// at AISlowCarSpeed or less (traffic, AISlowTrafficSpeed), or 2 for a
// traffic car whatever it passes. 0 with no car.
float drivingchoice_get_clearance(struct NearbyCarList *list,
                                  struct NearbyCar *nc,
                                  const FuturePointList *l, int32_t index);

// 0x00243f70, the demo's MakeDriveTargetParallelToCar, which retail hands
// the list. With both cars above 5 m/s, the other's three wheels on the
// ground and the two headed within 45 degrees, the other car's own target
// from its first point on, `side` across from it and kept on the road,
// until the target is full.
void drivingchoice_make_drive_target_parallel_to_car(
    const DrivingChoice *d, struct DriveTarget *t, struct NearbyCarList *list,
    const FuturePointList *l, float side);

// 0x00243aa8. A point beside the choice's car, with the clearance and the
// two half widths between them (4 m more with UseExtraLateralDistance), a
// smooth way out to it and, behind a player or traffic, the car's own
// target alongside; then the route ahead. 1 when it went round, 0 when
// the car is not on the route ahead or is 5 m or more off the road, and
// the target is only the route ahead. The float is not read.
int drivingchoice_build_drive_target_around_car(DrivingChoice *d,
                                                struct DriveTarget *t,
                                                struct NearbyCarList *list,
                                                float unused,
                                                struct DrivingLocation *loc);

// 0x00241ea0. The car's own target, emptied, then filled for the choice:
// the route ahead on the choice's line, or round its car. An invalid
// choice gets the route ahead on the location's line and 0; a line 1; a
// car what BuildDriveTargetAroundCar answers. Then the car's
// CarToExcludeFromCollisionPrediction is cleared. The floats are not read.
int drivingchoice_build_drive_target(DrivingChoice *d, struct DriveTarget *t,
                                     struct DrivingLocation *loc,
                                     struct NearbyCarList *list,
                                     float unusedA, float unusedB,
                                     MovementWithRespectToLine m);

// ------------------------------------------------ choosing a new choice

// 0x00241ff8. Builds `t` for the choice (BuildDriveTarget), scores it
// (EstimateScore, into `*score`, -1 first) and, when it scores above -1,
// asks CarCollisionPredict which car it runs into first (`*hitCar`,
// `*hitTime`, NULL and 99999 first). A `preferred` choice scores 1.2
// times as much and leaves its car out of the prediction; any other
// leaves none out (the controller's CarToExcludeFromCollisionPrediction,
// which BuildDriveTarget has just cleared). 1 when the first hit is later
// than `maxTime`. Bumps the world's PotentialDriveTargetID either way.
// `unusedA` goes to BuildDriveTarget, which does not read it; `unusedC`
// is not read.
int drivingchoice_is_driveable(DrivingChoice *d, struct DriveTarget *t,
                               int preferred, float *score, Car **hitCar,
                               float *hitTime, struct DrivingLocation *loc,
                               struct NearbyCarList *list, float unusedA,
                               float maxTime, float unusedC,
                               MovementWithRespectToLine m);

// 0x002428d0, a static of retail's, here for the checker. One try for
// MakeNewChoice: IsDriveable of `c` into `t`, towards the line, and when
// it is driveable and scores above `*bestScore`, `*found` is set and `c`,
// `t` and the score become the best (`*bestOut` 0). A side of the car
// `inTheWay`, without the extra distance, that is `preferred` is kept
// as the way round (`*round`, `*roundTarget`, `*roundTime` its first
// hit), driveable or not. 1 when the choice scored at all (not -1).
// With AITrafficTuningMode a traffic car only tries a side of an AI
// racer or a player's car, and answers 0 with nothing written for
// anything else. `unused` is not read.
int drivingchoice_try_choice(DrivingChoice *c, int preferred, float maxTime,
                             struct DrivingLocation *loc,
                             struct NearbyCarList *list, float unused,
                             int *found, struct DriveTarget *t,
                             DrivingChoice *best,
                             struct DriveTarget *bestTarget, int *bestOut,
                             float *bestScore, DrivingChoice *round,
                             struct DriveTarget *roundTarget,
                             float *roundTime, Car **hitCar, float *hitTime,
                             Car *inTheWay);

// 0x00242170. A new choice and its target, `t`. With `tryCurrent` the
// current choice is tried first (the choice if it is valid, else the
// location's line), preferred when it is the preferred side of its car;
// the car it runs into is then the car in the way. Then, if nothing yet,
// the first AICarControllerNumDrivingLinesToConsider driving lines; then
// both sides of every car we care about, and its preferred side with the
// extra distance for a car coming the other way of which neither side
// scored. The best score wins, `*out` 0. With none, a side of the car in
// the way that is no sooner hit than the current choice, less 0.1 s,
// `*out` 1; else the location's line filled up parallel to it, `*out` 0.
// `tryCurrent` also keeps each try from repeating the current choice.
// Answers whether one was found; the controller's car to leave out is
// fixed up from `*out`. `unused` is not read.
int drivingchoice_make_new_choice(DrivingChoice *d, struct DriveTarget *t,
                                  struct DrivingLocation *loc,
                                  struct NearbyCarList *list, float maxTime,
                                  float unused, int *out, int tryCurrent);

// 0x00242c20. A way round `nc`'s car, from `t` as it is: first the
// current choice (with `tryCurrent`, when it is valid, a side of this car
// or a line, and a line only when fast), then, when either car is above
// TryToDriveAroundCarMinSpeedForDrivingLine, the driving lines, then the
// preferred side of the car and the other, each only fast or with
// IsEnoughRoom. The first that IsDriveable takes is the choice, `*out`
// 1 for a preferred side; with none, the current choice if still valid
// or the location's line is built parallel to it and `*out` is left as
// it was. `a` goes to BuildDriveTarget unread; `unused` is not read.
int drivingchoice_try_to_drive_around_car(DrivingChoice *d,
                                          struct DriveTarget *t, int *out,
                                          struct NearbyCar *nc,
                                          struct DrivingLocation *loc,
                                          struct NearbyCarList *list, float a,
                                          float maxTime, float unused,
                                          int tryCurrent);

// 0x00241b88, the replay's (TASKS 72c), a "DrivingChoice" section: Type's
// low byte, the car by its number and UseExtraLateralDistance.
struct ReplaySnapshot;
void drivingchoice_do_snapshot(DrivingChoice *d, struct ReplaySnapshot *s);

#endif /* DRIVINGCHOICE_H */
