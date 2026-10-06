// aiaction -- AIPlan and the AIAction base: retail's AIPlan.hpp and
// AIAction.hpp, the part of the racer AI every action shares (step 11c).
//
// An AIAction is one thing an AI car can be doing: passing, avoiding cars,
// drafting, getting unstuck and the rest of AIActionType. AICarController
// scores the actions, keeps the best as CurrentAction, asks it each frame
// for the points to drive and the speed to drive them at, and asks it
// through UpdateStatus whether it is done. The subclasses are 11d's. This
// is the base: the plan's timeout and status, the record every action
// fills, the pool the actions come from, and the helpers the subclasses
// call.
//
// Retail's code is AIPlan.obj and AIAction.obj: InitAIPlans (0x001c6028)
// to AIAction's destructor (0x001c6b30), and the small methods from
// ClearPointsToDrive (0x001caa60) to AIPlan's constructor (0x001cac70).
// Not here:
// - DoSnapshot, AIPlan's (0x001c6088) and AIAction's two (0x001c6198 and
//   0x001c6268), which wait on ReplaySnapshot;
// - the out-of-line accessors (0x001caa98 to 0x001caaf4), which nothing
//   calls: the subclasses read the fields, and so does the port. The five
//   setters there (0x001caa70 to 0x001caa90) are empty in both images;
// - GetLateralDistance, which the demo has (0x001bc900) and retail does
//   not.
//
// Checked against retail by tools/nearbycar_check.py. Written up in
// docs/formats/ai-action.md.
#ifndef AIACTION_H
#define AIACTION_H

#include <stddef.h>
#include <stdint.h>

#include "bslotpool.h"
#include "bvector.h"
#include "car.h"
#include "collision.h"
#include "drivetarget.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "timer.h"

// 12AIActionType, type#1126, from the .mdebug.
typedef int32_t AIActionType;
#define AIACTION_PASS               ((AIActionType)0)
#define AIACTION_AVOID_CARS         ((AIActionType)1)
#define AIACTION_DRAFT              ((AIActionType)2)
#define AIACTION_BLOCK              ((AIActionType)3)
#define AIACTION_NUDGE_CAR          ((AIActionType)4)
#define AIACTION_JUST_DRIVE         ((AIActionType)5)
#define AIACTION_PULL_OVER          ((AIActionType)6)
#define AIACTION_GET_UNSTUCK        ((AIActionType)7)
#define AIACTION_AVOID_ROADBLOCK    ((AIActionType)8)
#define AIACTION_I_JUST_GOT_HIT     ((AIActionType)9)
#define AIACTION_ACCIDENT_RECOVERY  ((AIActionType)10)
#define AIACTION_NONE               ((AIActionType)11)

// PlanStatus, type#1102.
typedef int32_t PlanStatus;
#define STATUS_NOT_DONE  ((PlanStatus)0)
#define STATUS_SUCCESS   ((PlanStatus)1)
#define STATUS_FAILURE   ((PlanStatus)2)
#define STATUS_EXPIRED   ((PlanStatus)3)

// HeadingClassification, type#1115: whether a car is leaving its route,
// and which way it is pointing as it does.
typedef int32_t HeadingClassification;
#define HEADING_OKAY                     ((HeadingClassification)0)
#define HEADING_OUT_OF_ROUTE_FORWARDS    ((HeadingClassification)1)
#define HEADING_OUT_OF_ROUTE_BACKWARDS   ((HeadingClassification)2)
#define HEADING_NONE                     ((HeadingClassification)3)

// CollisionClassification, type#1116: where on a car it was hit.
typedef int32_t CollisionClassification;
#define COLLISION_IN_FRONT     ((CollisionClassification)0)
#define COLLISION_BEHIND       ((CollisionClassification)1)
#define COLLISION_LEFT_SIDE    ((CollisionClassification)2)
#define COLLISION_RIGHT_SIDE   ((CollisionClassification)3)
#define COLLISION_NONE         ((CollisionClassification)4)

// 20 bytes, type#1103, the same in both images. Its vptr is at 16, after
// the data, as g++ 2.9x puts it.
typedef struct AIPlan {
    int32_t    CanExpire;    //  0  a bool
    Timer      ExpiryTimer;  //  4  WorldTimer's ticks when the timeout was set
    float      DeltaTime;    //  8  the timeout, in seconds
    PlanStatus Status;       // 12
    uint32_t   _vtable;      // 16
} AIPlan;                    // 20

// Retail's 608 bytes. The demo's stab (type#1117) is 592: retail put a
// float at 572, after TimeToGetToDesiredSpeed, so everything from
// UseDrivingLineSpeed on is four bytes later than the demo's, and the
// record rounds up to 608, the subclasses' fields moving by sixteen.
//
// The float at 572 is the port's DesiredSpeedTolerance. The constructor
// zeroes it, and the subclasses that set it pass it to the driver's
// SetDesiredSpeed as a third float, within which PsychoDriver's
// CalcThrottleAndBrake coasts rather than use the throttle or the brake.
typedef struct AIAction {
    AIPlan       Base;                            //   0
    // The EE 16-aligns PointsToDrive; bVector3 carries no alignment of
    // its own here, so both pads are spelt out.
    uint8_t      _pad20[12];                      //  20
    DriveTarget  PointsToDrive;                   //  32
    int32_t      PointsToDriveWillExecuteAction;  // 560  a bool
    float        DesiredSpeed;                    // 564
    float        TimeToGetToDesiredSpeed;         // 568
    float        DesiredSpeedTolerance;           // 572  retail's
    int32_t      UseDrivingLineSpeed;             // 576  a bool
    int32_t      AllowedToUseThrottleAndBrake;    // 580  a bool
    int32_t      AllowedToUseBoost;               // 584  a bool
    AIActionType Type;                            // 588
    int32_t      Score;                           // 592
    uint8_t      _pad596[12];                     // 596  the round-up
} AIAction;                                       // 608

#ifndef AIACTION_NO_ASSERT
typedef char aiplan_layout_check[
    (offsetof(AIPlan, ExpiryTimer) == 4
     && offsetof(AIPlan, DeltaTime) == 8
     && offsetof(AIPlan, Status) == 12
     && offsetof(AIPlan, _vtable) == 16
     && sizeof(AIPlan) == 20) ? 1 : -1];
typedef char aiaction_layout_check[
    (offsetof(AIAction, PointsToDrive) == 32
     && offsetof(AIAction, PointsToDriveWillExecuteAction) == 560
     && offsetof(AIAction, DesiredSpeed) == 564
     && offsetof(AIAction, TimeToGetToDesiredSpeed) == 568
     && offsetof(AIAction, DesiredSpeedTolerance) == 572
     && offsetof(AIAction, UseDrivingLineSpeed) == 576
     && offsetof(AIAction, AllowedToUseThrottleAndBrake) == 580
     && offsetof(AIAction, AllowedToUseBoost) == 584
     && offsetof(AIAction, Type) == 588
     && offsetof(AIAction, Score) == 592
     && sizeof(AIAction) == 608) ? 1 : -1];
#endif

// The demo's tables, as the port's VTABLE constants all are: _vt$6AIPlan
// (retail 0x002b7cd0) and _vt$8AIAction (retail 0x002b7c90).
#define AIPLAN_VTABLE    0x0029b160u
#define AIACTION_VTABLE  0x0029b120u

// AIPlan's two slots, and AIAction's eight:
//
//      8  the destructor              40  HasBeenAccomplished (pure)
//     16  DoSnapshot                  48  HasFailed (pure)
//     24  CalculatePointsToDrive      56  HasExpired (pure)
//         (pure)
//     32  GetName
#define AIACTION_VT_DTOR                     8
#define AIACTION_VT_DO_SNAPSHOT             16
#define AIACTION_VT_CALCULATE_POINTS_TO_DRIVE 24
#define AIACTION_VT_GET_NAME                32
#define AIACTION_VT_HAS_BEEN_ACCOMPLISHED   40
#define AIACTION_VT_HAS_FAILED              48
#define AIACTION_VT_HAS_EXPIRED             56

#define AIPLAN_VT_ENTRIES    3
#define AIACTION_VT_ENTRIES  8

// The slot size of the pool: the largest action, and not AIAction's own
// 608. bNewSlotPool's 640 and 15 are retail's literals.
#define AIACTION_SLOT_SIZE   640
#define AIACTION_SLOTS       15

// "AIActionSlotPool", gp-18288. Every AIAction is new'd from it.
extern BSlotPool *AIActionSlotPool;

// 0x001c6028, from EndGameFlowLoadingTrackSpecific: makes the pool.
void ai_init_ai_plans(void);

// 0x001c6058, from BeginGameFlowUnloadingTrackSpecific: deletes the pool
// if there is one and clears the pointer, then tail-calls
// DestoryTargetMarkers on TheDriveTargetRenderer.
void ai_close_ai_plans(void);

// 0x001cac70. ExpiryTimer 0, the vptr, then SetTimeout. The constructor
// leaves Status as it was; nothing in either image constructs a bare
// AIPlan, and AIAction's constructor inlines this one and sets Status.
AIPlan *aiplan_init(AIPlan *p, float timeout);

// 0x001cac48. The vptr, then `__builtin_delete` when flags & 1. Its one
// caller, AIAction's destructor, passes 0.
void aiplan_destroy(AIPlan *p, int32_t flags);

// 0x001cab90. CanExpire is `0 <= timeout`, DeltaTime the timeout, and
// ExpiryTimer WorldTimer in seconds and back in ticks, rounded.
void aiplan_set_timeout(AIPlan *p, float timeout);

// 0x001cab48. True for no plan, a plan that succeeded or failed, or one
// that expired and can.
int aiplan_time_to_change(const AIPlan *p);

// 0x001cabf0 to 0x001cac28. No callers in either image, but cheap.
PlanStatus aiplan_get_status(const AIPlan *p);
int aiplan_is_not_done(const AIPlan *p);
int aiplan_failure(const AIPlan *p);
int aiplan_success(const AIPlan *p);
int aiplan_is_expired(const AIPlan *p);   // EXPIRED and CanExpire

// 0x001c6118, AIAction(int score, float timeout). AIPlan's constructor
// inline, AIAction's vptr, PointsToDrive's constructor, and then Score,
// Status 0, the three speeds and the tolerance 0, and the three
// permissions 1. PointsToDriveWillExecuteAction and Type are the
// subclasses'.
AIAction *aiaction_init(AIAction *a, int32_t score, float timeout);

// 0x001c6b30. The vptr, PointsToDrive's destructor, AIPlan's with 0, and
// the pool's bFree when flags & 1.
void aiaction_destroy(AIAction *a, int32_t flags);

// 0x001cab08 (and 0x001cab28, the named overload, which is the same):
// operator new, a slot from AIActionSlotPool.
void *aiaction_new(void);

// 0x001caaf8: operator delete, the slot back to AIActionSlotPool.
void aiaction_delete(void *p);

// 0x001c6a98. Status NOT_DONE; then EXPIRED if HasExpired, FAILURE if
// HasFailed and SUCCESS if HasBeenAccomplished, each asked through the
// vptr and each overriding the last.
void aiaction_update_status(AIAction *a, DrivingInformation *info);

// 0x001c64e8. A speed `delta` below the car's, not below 0, reached by the
// time the gap closes at the car's apparent closing speed, but not in
// under 0.1 s. The last float is never read.
void aiaction_set_desired_speed_slower_than_this_car(AIAction *a,
                                                     NearbyCar *nc,
                                                     NearbyCarList *list,
                                                     float delta,
                                                     float unused);

// 0x001c6530 and 0x001c6588. The speed the car reaches in `t` seconds at
// its most acceleration or deceleration, from its speed now.
void aiaction_set_desired_speed_to_max_acceleration(AIAction *a, Car *car,
                                                    float t);
void aiaction_set_desired_speed_to_max_deceleration(AIAction *a, Car *car,
                                                    float t);

// 0x001c65e0, a static method. Whether `car` is leaving the road at
// loc's point: OKAY, or OUT_OF_ROUTE_FORWARDS or _BACKWARDS by the way
// the car is moving. A forwards car whose driver's steer-to point is ahead
// of it is OKAY when `steer_check` is set, and a backwards car pointing
// within 70 degrees of the route is OKAY.
HeadingClassification aiaction_get_heading_classification(
    DrivingLocation *loc, Car *car, int steer_check);

// 0x001c69d8, a static method. Where on the car the collision's contact
// point is: IN_FRONT or BEHIND when its car-space x lies within 95% of
// the box's y extents, else a side. Retail holds x against y.
CollisionClassification aiaction_get_collision_classification(
    Collision *coll, Car *car);

// 0x001caa60. PointsToDrive's Clear(NULL, 0).
void aiaction_clear_points_to_drive(AIAction *a);

// 0x001caae0. "", which every action overrides.
const char *aiaction_get_name(AIAction *a);

// Installs AIPlan's and AIAction's tables. The pure slots and the
// DoSnapshots are NULL.
void aiaction_install_vtables(void);

#endif
