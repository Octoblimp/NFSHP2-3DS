// aicarcontroller -- AICarController, the controller of a car the AI
// drives: retail's AICarController.obj, 0x00190140 to 0x00194058.
//
// The base of AIDriver's and TrafficDriver's controllers (steps 11f and
// on). It keeps the car's DrivingInformation (its nearby cars, where on
// the route it is and the choice it drives by), the AIAction it is
// carrying out, and the timers and averages its Think reads. DrivingChoice
// (step 11b) and the actions (11c, 11d) read and write it.
//
// Step 11e ports it in slices. 11e-1 has the record, the constructor and
// destructor, the table, the route methods, JustReset, the action's
// interruption and points, the physics mode, the line speed, the boosts
// and the small accessors. The sticky decisions and signposts are 11e-2's,
// the belt, glue and boost decisions 11e-3's, the honking and
// ExecuteCurrentAction 11e-4's, and Think 11e-5's. AIAction is in
// aiaction.h (11c). docs/formats/ai-car-controller.md has the detail.
//
// The offsets are retail's. They agree with the demo's stab (type#1344,
// 704 bytes) up to aStickyDecisions at 652, which retail makes eight words
// (the demo's six); two words of retail's own follow, and pDeltaLineSpeed
// and vPreviousLinePoint move from 676 and 688 to 692 and 704. 720 bytes.
#ifndef AICARCONTROLLER_H
#define AICARCONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#include "aiaction.h"
#include "average.h"
#include "bvector.h"
#include "car.h"
#include "carcontroller.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "timer.h"
#include "trackroute.h"

struct Player;

// A sticky decision: what the car decided at a signpost, kept until it is
// past it. Bit 0 says the slot is in use; the rest are 11e-2's.
#define AICC_NUM_STICKY_DECISIONS 8

typedef struct AICarController {
    CarController       Base;                               //   0
    DrivingInformation  MyCurrentDrivingInformation;        //  12
    DrivingLocation    *CurrentDrivingLocation;             // 504
    DrivingChoice      *CurrentDrivingChoice;               // 508
    NearbyCarList      *CurrentNearbyCarList;               // 512
    Car                *CarToExcludeFromCollisionPrediction;// 516
    int8_t              LastTrackRouteNumber;               // 520
    float               SecondsBeforeNextActionEvaluation;  // 524
    AIActionType        ForceCurrentAction;                 // 528
    AIAction           *CurrentAction;                      // 532
    Timer               LastRoutePointLookaheadSwitch;      // 536
    int32_t             CurrentRoutePointLookahead;         // 540
    Timer               LastTimeNonGetUnstuckActionWasCalled; // 544
    float               PullOverTimeout;                    // 548
    Timer               BrakeStandTimer;                    // 552
    Timer               BrakeStandTimerStart;               // 556
    int32_t             BrakeStanding;                      // 560  a bool
    Timer               LastBoostCalculationTime;           // 564
    Timer               OffBeltTimer;                       // 568
    Timer               RealPhysicsTimer;                   // 572
    Timer               ProgressTimer;                      // 576
    Average            *pProgress;                          // 580
    float               fLastProgress;                      // 584
    Car                *pGlueCar;                           // 588
    Timer               GlueOnTimer;                        // 592
    Timer               GlueOffTimer;                       // 596
    int32_t             nGlueOffReason;                     // 600
    float               fCurrentGlueTimeBias;               // 604
    char                sGlueDebug[32];                     // 608
    int32_t             bBoostAllowed;                      // 640  a bool
    struct Player      *pCatchupPlayer;                     // 644
    int32_t             nSignpostIndex;                     // 648
    uint32_t            aStickyDecisions[AICC_NUM_STICKY_DECISIONS]; // 652
    // Retail's own, with no stab to name them. 684 is the signpost whose
    // route the car has taken and whose line speed ExecuteCurrentAction
    // reads (-1 none); 688 is a timer GetCurrentTrackRoutePoint sets when
    // it takes a sign's route and ExecuteCurrentAction tests.
    int32_t             TakenSignpostIndex;                 // 684
    Timer               TakenSignpostTimer;                 // 688
    Average            *pDeltaLineSpeed;                    // 692
    // vPreviousLinePoint is a quadword, 16-aligned on the EE.
    uint8_t             _pad696[8];                         // 696
    bVector3            vPreviousLinePoint;                 // 704
} AICarController;                                          // 720

#ifndef AICARCONTROLLER_NO_ASSERT
typedef char aicarcontroller_layout_check[
    (sizeof(void *) != 4
     || (offsetof(AICarController, MyCurrentDrivingInformation) == 12
         && offsetof(AICarController, CurrentDrivingLocation) == 504
         && offsetof(AICarController, CurrentDrivingChoice) == 508
         && offsetof(AICarController, CurrentNearbyCarList) == 512
         && offsetof(AICarController,
                     CarToExcludeFromCollisionPrediction) == 516
         && offsetof(AICarController, LastTrackRouteNumber) == 520
         && offsetof(AICarController,
                     SecondsBeforeNextActionEvaluation) == 524
         && offsetof(AICarController, ForceCurrentAction) == 528
         && offsetof(AICarController, CurrentAction) == 532
         && offsetof(AICarController, LastRoutePointLookaheadSwitch) == 536
         && offsetof(AICarController, PullOverTimeout) == 548
         && offsetof(AICarController, BrakeStanding) == 560
         && offsetof(AICarController, ProgressTimer) == 576
         && offsetof(AICarController, pProgress) == 580
         && offsetof(AICarController, pGlueCar) == 588
         && offsetof(AICarController, sGlueDebug) == 608
         && offsetof(AICarController, bBoostAllowed) == 640
         && offsetof(AICarController, nSignpostIndex) == 648
         && offsetof(AICarController, aStickyDecisions) == 652
         && offsetof(AICarController, TakenSignpostIndex) == 684
         && offsetof(AICarController, TakenSignpostTimer) == 688
         && offsetof(AICarController, pDeltaLineSpeed) == 692
         && offsetof(AICarController, vPreviousLinePoint) == 704
         && sizeof(AICarController) == 720)) ? 1 : -1];
#endif

// A car's controller as an AI one. Only for a car under AI control:
// nothing checks.
static inline AICarController *car_ai_controller(Car *c)
{
    return (AICarController *)(void *)c->pCarController;
}

// _vt$15AICarController, retail's 0x002b4d90 (the port keys it by the
// demo's, carcontroller.h's AICARCONTROLLER_VTABLE). CarController's
// thirteen slots and three of its own: 112 GetRouteNumbersToUse (pure:
// AIDriver's and TrafficDriver's), 120 ChooseNewAction (`jr ra` here) and
// 128 GeneratePointsToFulfillAction.
#define AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE         112
#define AICARCONTROLLER_VT_CHOOSE_NEW_ACTION                120
#define AICARCONTROLLER_VT_GENERATE_POINTS_TO_FULFILL_ACTION 128

// Seventeen entries, the empty header included.
#define AICARCONTROLLER_VT_ENTRIES 17

typedef void (*AICarControllerRouteNumbersFn)(void *self, int32_t *first,
                                              int32_t *last);
typedef void (*AICarControllerChooseFn)(void *self, AIAction **out,
                                        AIActionType type);
typedef void (*AICarControllerGenerateFn)(void *self, AIAction *a);

// -------------------------------------------------------- the record

// 0x00190140. The base's constructor and the record's: the nearby list
// emptied (each entry's car NULL, MyCar the car), the location, choice
// and information Cleared, the timers zeroed, the sticky decisions' bit 0
// cleared, SecondsBeforeNextActionEvaluation the car's index (lh at 8)
// times -1/140, no forced action (11), no current action,
// LastTrackRouteNumber -1, ProgressTimer 1.5 s, the progress and line
// speed Averages (10 and 5 slots, bMalloc'd), vPreviousLinePoint zero,
// the boost allowed, PullOverTimeout 1e7, BrakeStanding set, the signpost
// the car's distance round the track is at, and no taken signpost.
// fLastProgress, fCurrentGlueTimeBias, sGlueDebug, the sticky decisions'
// other bits and the Driver are not written.
AICarController *aicarcontroller_init(AICarController *c, Car *car);

// 0x001903a0. The current action deleted through its table, the two
// Averages destroyed (each if there is one), then CarController's
// destructor with `flags`.
void aicarcontroller_destroy(AICarController *c, int32_t flags);

// 0x00191138. Nothing.
void aicarcontroller_debug_display(AICarController *c);

// -------------------------------------------------------- the route

// 0x00190670. With a route and a point: LastTrackRouteNumber the old
// route's number (-1 with none), then the location set to the new route
// and point, relaxed, on the line GetNewDrivingLine picks.
void aicarcontroller_set_current_route(AICarController *c, TrackRoute *r,
                                       TrackRoutePoint *p);

// 0x00190708 / 0x00190760. The location's route and point. With `find`
// and the location clear, FindWhereIAm first, through the table. Retail's
// Car::GetRoute and GetRoutePoint pass the flag through.
TrackRoute *aicarcontroller_get_current_route(AICarController *c, int find);
TrackRoutePoint *aicarcontroller_get_current_route_point(AICarController *c,
                                                         int find);

// 0x001907b8. 0 with the location clear; otherwise how far the car is past
// its point's road, across the point's direction, less the width that
// side (negative inside).
float aicarcontroller_get_amount_out_of_bounds(AICarController *c);

// 0x00192f10. The location Cleared, then FindClosestTrackRoute over the
// route numbers GetRouteNumbersToUse gives (both arms of the control mode
// 3 test make the same call).
void aicarcontroller_find_where_i_am(AICarController *c);

// 0x00190900. The nearest point of routes `first` to `last` within
// 999999, in two passes: first only the routes whose stretch holds the
// car's distance round the track, then any. A route that is the
// location's own is passed over. With one found, SetCurrentRoute through
// the table; otherwise the location is Cleared.
void aicarcontroller_find_closest_track_route(AICarController *c,
                                              int32_t first, int32_t last);

// 0x00192488. The first of the lines 1 to
// AICarControllerNumDrivingLinesToConsider whose choice is driveable from
// `p` (IsDriveable, within AIDriverAvoidCarsImpactTimeThreshold), into
// `*line`, and 1; else 0 with `*line` line 1's. With a route and a point
// and a `highlight` location, that location's line is highlighted with my
// driver number.
int aicarcontroller_get_new_driving_line(AICarController *c, TrackRoute *r,
                                         TrackRoutePoint *p, int relaxed,
                                         int32_t *line,
                                         DrivingLocation *highlight);

// 0x00190850. SecondsBeforeNextActionEvaluation as the constructor sets
// it, vPreviousLinePoint zero, the driver's ZeroSteeringMemory, the
// sticky decisions cleared and the signpost found again.
void aicarcontroller_just_reset(AICarController *c);

// 0x001908f0. The car's DriverNumber.
int32_t aicarcontroller_get_my_driver_number(AICarController *c);

// 0x00191d10. Bit 0 of each of the eight cleared.
void aicarcontroller_clear_sticky_decisions(AICarController *c);

// 0x00192848. The driver steers to the point a metre ahead of the car,
// along its heading.
void aicarcontroller_steer_straight_ahead(AICarController *c);

// -------------------------------------------------------- the action

// 0x00192780. `jr ra`: AIDriver's and TrafficDriver's choose.
void aicarcontroller_choose_new_action(AICarController *c, AIAction **out,
                                       AIActionType type);

// 0x00192788. With no forced action, the action ChooseNewAction makes
// for 11, or NULL: kept only when there is a current action scoring less
// than it, else deleted. With one, the action made for it, and the force
// is dropped.
AIAction *aicarcontroller_interrupt_action(AICarController *c);

// 0x00192668. The action's CalculatePointsToDrive. When its points will
// not carry it out, the current action is deleted and replaced with
// ChooseNewAction's for type 2, whose points are calculated (its result
// is not tested). Then, when the choice is a driving line other than the
// location's, the location takes it, not relaxed, and is highlighted.
// The car ahead is looked up first and not used.
void aicarcontroller_generate_points_to_fulfill_action(AICarController *c,
                                                       AIAction *a);

// 0x00194000. The current action's type, or 11.
AIActionType aicarcontroller_get_current_action_type(AICarController *c);

// 0x00194020.
void aicarcontroller_force_my_current_action(AICarController *c,
                                             AIActionType type);

// -------------------------------------------------------- the physics

// 0x00193650. Off the belt (mode 6), OffBeltTimer 2 s. The mode is
// nDefaultMovementMode, or physics when `car` is a player's; when that is
// not the car's own, SetMovementMode. Physics also sets RealPhysicsTimer
// 3 s.
void aicarcontroller_set_to_physics_mode(AICarController *c, Car *car);

// 0x001936f0. 0 with the location clear, else the line's speed byte at
// the location's point.
float aicarcontroller_get_current_driving_line_speed(AICarController *c);

// car.h's seam takes the base.
float aicarcontroller_line_speed_seam(CarController *ctl);

// 0x00193758 / 0x00193780. The base's, then the boost disallowed or
// allowed again.
void aicarcontroller_force_boost(AICarController *c, float f);
void aicarcontroller_release_boost(AICarController *c);

// 0x00191130. 0.
int32_t aicarcontroller_about_to_fly(AICarController *c, float t);

// 0x00194028. OffBeltTimer, `seconds` from now.
void aicarcontroller_set_off_belt_timer(AICarController *c, float seconds);

// 0x00193fe0 / 0x00193fe8 / 0x00193ff8.
Car *aicarcontroller_get_car_to_exclude_from_collision_prediction(
    AICarController *c);
void aicarcontroller_set_car_to_exclude_from_collision_prediction(
    AICarController *c, Car *car);
DrivingLocation *aicarcontroller_get_current_driving_location(
    AICarController *c);

void aicarcontroller_install_vtables(void);

#endif /* AICARCONTROLLER_H */
