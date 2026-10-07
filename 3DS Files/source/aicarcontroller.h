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
// and the small accessors. 11e-2 has the sticky decisions and signposts,
// SignPostDecision among them (main.c points drivingchoice.h's seam at
// it). 11e-3 has the belt, the glue and the boost: whether the car may
// go on the belt or glue itself to a player, the glued speed, and the
// catchup boost. The honking and ExecuteCurrentAction are 11e-4's, and
// Think 11e-5's. AIAction is in aiaction.h (11c).
// docs/formats/ai-car-controller.md has the detail.
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
#include "graph.h"
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

// -------------------------------------------------------- the signposts
//
// A sticky decision is a word: bit 0 the slot in use, bit 1 the sign
// taken, bits 2 to 7 the line (0 or 1, or the location's), bits 8 to 15
// the sign's index in SignpostArray.

// 0x00191d40. nSignpostIndex on past every sign behind the car's distance
// round the track (`c.lt.s`), stopping at 0 when it wraps.
void aicarcontroller_find_signpost_index(AICarController *c);

// 0x00191d90. The first sticky decision not in use, or -1.
int32_t aicarcontroller_get_sticky_index(AICarController *c);

// 0x00191b30. Each decision in use more than 10 m past its sign is
// dropped, and TakenSignpostIndex with it when it is that sign's. Then,
// while a slot is free, the signs from nSignpostIndex on: one behind is
// passed, one within AIDriverSecondsToLookAhead times my speed times 1.1
// (100 to 250 m) is decided with a line of -1 and passed, and the first
// further on stops it.
void aicarcontroller_do_sticky_decisions(AICarController *c);

// 0x00191de0. Whether to take sign `s` onto its new route, and the line
// to drive there through `line`. A Backwards sign, or a Cloaked one but
// for AlwaysTake, is not taken and keeps the location's line (line 0's
// with the location clear) without a decision. A sign already decided
// answers its decision. Otherwise: AlwaysTake is taken; any other only
// past the grace period (the track's SignpostGracePeriod on the race
// clock, or Race::GracePeriodIsActive with -1 there); then Equivalent on
// a coin flip (World::Random under 0.5), DontTake never, and the rest by
// my skill's TakeSignChance. A sign taken but AlwaysTake needs
// GetNewDrivingLine to find a driveable line on its route (relaxed, `loc`
// highlighted), else it is not taken; an AIHint 2 sign it takes becomes
// TakenSignpostIndex. A sign taken still with a negative line asks
// GetNewDrivingLine for one. A line other than 0 or 1 becomes the one a
// sign not taken keeps. The decision goes in the first free slot, and with
// none free, over nSignpostIndex, as retail's -1 slot lands there.
int aicarcontroller_sign_post_decision(AICarController *c, Signpost *s,
                                       int32_t *line, DrivingLocation *loc);

// 0x001921f8. With the location clear, or the car further past its
// point's road than MyHalfSizeL either side, FindWhereIAm (through the
// table). Otherwise the location moves to the first point ahead of the
// car (the route's last with none ahead), and the signs on the points
// from the old to the new are decided in turn: the first taken puts the
// location on the sign's route and point, relaxed, LastTrackRouteNumber
// the old route's, and an AIHint 1 sign sets TakenSignpostTimer to 10000
// ticks. At the route's end with no sign taken, FindWhereIAm. `car` is
// not read.
void aicarcontroller_get_current_track_route_point(AICarController *c,
                                                   Car *car);

// ------------------------------------------ the belt, the glue and the boost

// The unit's globals: bBeltMover (gp-20344, 1), the glue's boost graph
// (gp-20336, (-20, 0.1) to (20, -0.1)), CarControllerDisableCatchup
// (gp-20132, 0) and nLastGlueReason (gp-20296), the reason the last
// WeCanHaveTheGlue said no.
extern int32_t bBeltMover;
extern Graph   gGlueBoostGraph;
extern int32_t CarControllerDisableCatchup;
extern int32_t nLastGlueReason;

// 0x00190af8. The car's movement mode is the belt's (6).
int aicarcontroller_we_have_the_belt(AICarController *c);

// 0x00190b10. bBeltMover.
int aicarcontroller_we_need_the_belt(AICarController *c);

// 0x00190b20. Whether the car may go on the belt: a drive target of three
// points or more, the race coordinator not in its AI demo, neither
// OffBeltTimer nor RealPhysicsTimer set, at least 5 m/s forward with a
// wheel down, an action that isn't PullOver, GetUnstuck, AvoidRoadBlock,
// IJustGotHit or AccidentRecovery, a driver who isn't careful (skill -2),
// no player within 120 m and the race 30 s old.
int aicarcontroller_we_can_have_the_belt(AICarController *c);

// 0x00190c78 / 0x00190c88. A glued car; and 0, as retail's `jr ra`.
int aicarcontroller_we_have_the_glue(AICarController *c);
int aicarcontroller_we_need_the_glue(AICarController *c);

// 0x00190c90. Whether the car may glue itself to `p`'s car, or, with the
// glue on, keep it on the glued car's own player: an action before
// PullOver and the player's speed ratio no less than 0.94; held while
// GlueOnTimer runs within 60 m, 10 m/s and a heading dot of 0.5 (the end
// of GlueOnTimer starts GlueOffTimer, 20 s); taken with GlueOffTimer not
// set, within 30 m, 6 m/s and 0.7, the player's car not ahead. Each no
// leaves its reason in nLastGlueReason.
int aicarcontroller_we_can_have_the_glue(AICarController *c,
                                         struct Player *p);

// 0x00190f38. With no glue: the player's nGlueCount up one, GlueOnTimer
// 7 s, the player's car glued, fCurrentGlueTimeBias 0.2.
void aicarcontroller_glue_on(AICarController *c, struct Player *p);

// 0x00190fb8. With glue: unglued, and its player's nGlueCount down one.
void aicarcontroller_glue_off(AICarController *c);

// 0x00190ff8. The glued car's speed by the gap to it (negative with it
// ahead in the race, less the bias times its speed), through the glue
// graph and the speed difference, within 0.9 and 1.1 of its speed. With
// either car out of the race, the driver's GetDesiredSpeed.
float aicarcontroller_get_glue_speed(AICarController *c);

// 0x00192c78. With the race's boost on, how much the car (`me`) is behind
// `them` (a lap fraction within half a lap either way for a cop race, the
// track's length times that) up to MaxDistanceForBoost, through the
// distance graphs between the low and high skill, plus a term for the
// speeds within 0.05 either way, into `dist`; the position boost for
// their places into `pos`. Both 0 otherwise.
void aicarcontroller_calculate_distance_and_position_boost(
    AICarController *c, struct RacingCar *me, struct RacingCar *them,
    float *dist, float *pos);

// 0x001928f0. For an AI car in the race with the boost allowed, every
// BoostCalculationFrequency seconds: the catchup boost to the player (one
// player), or the lead or trailing player by place (two), past the
// race's first 30 s and with the action's AllowedToUseBoost; then, for a
// player with a full average short of its best, its speed ratio by the
// table for its place and the car's skill, no lower than the skill's
// SlowFactor. Into the car's BoostFactor.
void aicarcontroller_decide_boost_factor(AICarController *c);

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
