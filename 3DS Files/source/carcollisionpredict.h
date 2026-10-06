// carcollisionpredict -- CarCollisionPredict, which car an AI car's
// DriveTarget would run it into, and when: retail's
// CarCollisionPredict.obj (0x001e5e60 .. 0x001e7930) as far as it is
// alive.
//
// The class has no fields (the .mdebug gives it one byte) and nothing
// reads its `this`, so the port's functions take none. Retail's callers
// are AIActionAvoidCars::CalculateScore, AIActionPullOver's and
// AIActionAvoidRoadBlock's CalculatePointsToDrive and
// DrivingChoice::IsDriveable, all through WhoWillThisDriveTargetHit.
//
// The prediction: each car's target is turned into a chain of boxes, one
// per point, as wide as the car's own bounding box (scaled), the first
// along the car and the rest along the legs between the points. Then the
// two cars are walked along their chains together at their own speeds,
// one leg at a time, and each step asks when the two current boxes would
// first overlap on the ground if both kept their velocities. The first
// overlap within the step is the hit.
//
// OBBOverlap2D, OBBOverlap3D, SeparatingAxisTest and TimeToImpact are in
// the image too, and nothing calls them; the port leaves them out.
//
// Checked against retail by tools/drivingchoice_check.py. Written up in
// docs/formats/ai-collision-predict.md.
#ifndef CARCOLLISIONPREDICT_H
#define CARCOLLISIONPREDICT_H

#include <stdint.h>

#include "bvector.h"
#include "car.h"
#include "obb.h"

struct DriveTarget;
struct DrivingLocation;
struct NearbyCar;
struct NearbyCarList;

// 0x001e5e60. Of the cars on `list` worth caring about
// (ai_do_we_care_about_this_car), the one `t` would run my car into
// first, or NULL; `*when` is the time, 99999 with none. A car stopped
// just ahead counts at 0. My car going no faster than 0.001 m/s, or the
// car my controller leaves out, never counts. Bumps the world's
// CollisionPredictionID once for every car it cares about. With no
// location, a clear one, or a target of no points or more than 20, it
// answers NULL and leaves `*when` alone.
Car *ccp_who_will_this_drive_target_hit(struct DriveTarget *t,
                                        struct NearbyCarList *list,
                                        struct DrivingLocation *loc,
                                        float maxTime, float *when);

// 0x001e60a0. Whether my car, on `t`, hits `other`, on its own target,
// within `maxTime` seconds; `*when` is the time, 99999 with no hit. `loc`
// is never read. Retail keeps the two targets' copies and forty boxes on
// its stack, 4720 bytes; the port keeps them in static storage.
int ccp_will_i_hit_this_car(struct DriveTarget *t,
                            struct DrivingLocation *loc, Car *me,
                            Car *other, float maxTime, float *when);

// 0x001e6010. A car going no faster than 5 m/s, overlapping mine across
// and less than both half lengths plus 23 m ahead.
int ccp_is_this_car_stopped_directly_in_front_of_me(
    struct NearbyCar *nc, struct NearbyCarList *list);

// 0x001e6860. A box for each of `t`'s points, the car's bounding box's
// half sizes times `scale`: the first along the car's angle, each other
// along the leg back to the point before. Nothing for a NULL target,
// boxes or car, or a target of no points.
void ccp_make_obbs_for_drive_target(struct DriveTarget *t, OBB *obbs,
                                    Car *car, float scale);

// 0x001e72f8. When two boxes `d` apart (b's centre less a's), closing at
// `v` (b's velocity less a's), first overlap in x and y: the latest entry
// on the four axes (each box's first two), when they all overlap. 0 when
// they overlap now and still will; 99999 when they never do, or touch at
// 0 exactly.
float ccp_when_will_overlap_occur_2d(OBB *a, OBB *b, const bVector3 *d,
                                     const bVector3 *v);

// 0x001e7238. The times when a gap of `d` closing at `v` is within `r`
// on one axis, in order. Under 0.0001 m/s it is all time (-9999, 9999)
// when `d` is within `r`, else never (9999, 9999).
void ccp_time_interval_for_separating_axis(float v, float d, float r,
                                           float *tmin, float *tmax);

// 0x001e6ac0. Whether [a0, a1] and [b0, b1] overlap: the four ends
// sorted, and the second lies in both. Then `*lo` and `*hi` are the
// second and third.
int ccp_interval_overlap(float a0, float a1, float b0, float b1, float *lo,
                         float *hi);

#endif /* CARCOLLISIONPREDICT_H */
