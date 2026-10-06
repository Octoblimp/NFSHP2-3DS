// aiactions -- the AIAction subclasses, retail's AIAction.obj after the
// base (step 11d). Each is one thing an AI car can be doing; AIDriver's
// ChooseNewAction scores them with the static CalculateScores, news the
// best from AIActionSlotPool (aiaction.h) and makes it CurrentAction,
// and the controller asks it each frame for its points and speed through
// the vptr.
//
// Here (11d-1), the five small ones:
// - JustDrive (0x001c73c0 .. 0x001c768c): the route ahead on driving line
//   0, going back to that line at most every three seconds when it is
//   driveable;
// - Draft (0x001c7690 .. 0x001c78f4): the route ahead, slowing to sit
//   behind the car just in front when it is within 6 m and overlaps;
// - NudgeCar (0x001c8028 .. 0x001c815c) and Block (0x001c8160 ..
//   0x001c8294), which carry a car and do nothing with it;
// - AccidentRecovery (0x001ca1f0 .. 0x001ca524): stopped on the route
//   until the car is back on its wheels, and reset after five seconds of
//   not.
// Their GetNames and destructors are 0x001ca5b8 to 0x001ca974.
//
// And 11d-2's two:
// - Pass (0x001c78f8 .. 0x001c8024): round a car ahead that can be
//   caught, until it is ten metres behind;
// - AvoidCars (0x001c6ba0 .. 0x001c73bc): a new choice round the car my
//   own target runs into, re-made every 0.3 s, slowing behind that car
//   when there is no way round.
// Their GetNames, destructors and GetCarToAvoid are 0x001ca978 to
// 0x001caa5c.
//
// And 11d-3a's two:
// - PullOver (0x001c8298 .. 0x001c8b2c): a traffic car near a cop's
//   lights or the chopper edges to the right side of the road and stops;
// - IJustGotHit (0x001c9c68 .. 0x001ca1ec): new choices every 0.2 s while
//   touching a car, the speed by where that car is.
// Their GetNames and destructors are 0x001ca628 to 0x001ca7e4.
//
// And 11d-3b's two:
// - GetUnstuck (0x001c8b30 .. 0x001c9664): a car off the road, heading
//   out of it, stuck behind a slow car or nosed into something backs
//   towards a point three ahead on its line until it faces it;
// - AvoidRoadBlock (0x001c9668 .. 0x001c9c64): a car closing on a manned
//   roadblock steers onto its escape lane, slowing behind a racer in the
//   way.
// Their GetNames and destructors are 0x001ca698 to 0x001ca774. The
// DoSnapshots wait on ReplaySnapshot.
//
// Checked against retail by tools/drivingchoice_check.py. Written up in
// docs/formats/ai-action.md.
#ifndef AIACTIONS_H
#define AIACTIONS_H

#include <stddef.h>
#include <stdint.h>

#include "aiaction.h"
#include "car.h"
#include "copmanager.h"
#include "nearbycar.h"
#include "timer.h"

// AIDriverAvoidCarsImpactTimeThreshold (gp-18168, 0x003311f8), 2.0f, in
// AIDriver.obj's .sdata: the longest time to a hit that still lets a
// choice count as driveable. Nothing writes it. JustDrive passes it to
// IsDriveable; AvoidCars, Pass, PullOver, IJustGotHit and
// AICarController's Think and GetNewDrivingLine read it too.
extern float AIDriverAvoidCarsImpactTimeThreshold;

// ---------------------------------------------------------- the records

// The demo's stabs (types #1216, #1184, #1195, #1206 and #1279), with each
// field sixteen bytes later than the demo's, after retail's 608-byte base.
typedef struct AIActionJustDrive {
    AIAction Base;                              //   0
    Timer    LastDecisionReevaluationTime;      // 608
} AIActionJustDrive;

typedef struct AIActionDraft {
    AIAction Base;                              //   0
} AIActionDraft;

typedef struct AIActionNudgeCar {
    AIAction Base;                              //   0
    Car     *CarToNudge;                        // 608
} AIActionNudgeCar;

typedef struct AIActionBlock {
    AIAction Base;                              //   0
    Car     *CarToBlock;                        // 608
} AIActionBlock;

typedef struct AIActionAccidentRecovery {
    AIAction Base;                              //   0
    Timer    MyCreationTime;                    // 608
    int32_t  HaveResetYet;                      // 612  a bool
} AIActionAccidentRecovery;

// 11d-2's. The bools are words, as the image stores them.
typedef struct AIActionPass {
    AIAction Base;                              //   0
    Car     *CarToPass;                         // 608
    float    AmountToProjectIntoFuture;         // 612
    Timer    MyCreationTime;                    // 616
} AIActionPass;

typedef struct AIActionAvoidCars {
    AIAction Base;                              //   0
    Car     *CarToAvoid;                        // 608
    float    SecondsToImpact;                   // 612
    int32_t  IsMyDrivingChoiceOkay;             // 616  a bool
    Timer    LastDecisionReevaluationTime;      // 620
    Timer    MyCreationTime;                    // 624
    float    MinLifetime;                       // 628
    int32_t  UsedPreferredSide;                 // 632  a bool
} AIActionAvoidCars;

// 11d-3a's. PullOver's word at 620 is retail's: whether there is room to
// pull over to the right, set over 4 m to the edge and cleared under 2.
// PullOverTimeout moved past it.
typedef struct AIActionPullOver {
    AIAction Base;                              //   0
    Timer    MyCreationTime;                    // 608
    Timer    LastDecisionReevaluationTime;      // 612
    int32_t  IsMyDrivingChoiceOkay;             // 616  a bool
    int32_t  New620;                            // 620  a bool
    float    PullOverTimeout;                   // 624  -999 for none
} AIActionPullOver;

typedef struct AIActionIJustGotHit {
    AIAction Base;                              //   0
    Car     *CarIHit;                           // 608
    Timer    LastDecisionReevaluationTime;      // 612
} AIActionIJustGotHit;

// 11d-3b's.
typedef struct AIActionGetUnstuck {
    AIAction Base;                              //   0
    Timer    MyCreationTime;                    // 608
    float    MinimumLifetime;                   // 612
    int32_t  MinimumLifetimeInEffect;           // 616  a bool
} AIActionGetUnstuck;

typedef struct AIActionAvoidRoadBlock {
    AIAction          Base;                     //   0
    const tRoadBlock *RoadBlockToAvoid;         // 608
} AIActionAvoidRoadBlock;

#ifndef AIACTION_NO_ASSERT
typedef char aiactions_layout_check[
    (offsetof(AIActionJustDrive, LastDecisionReevaluationTime) == 608
     && offsetof(AIActionNudgeCar, CarToNudge) == 608
     && offsetof(AIActionBlock, CarToBlock) == 608
     && offsetof(AIActionAccidentRecovery, MyCreationTime) == 608
     && offsetof(AIActionAccidentRecovery, HaveResetYet) == 612
     && sizeof(AIActionAccidentRecovery) <= AIACTION_SLOT_SIZE
     && offsetof(AIActionPass, CarToPass) == 608
     && offsetof(AIActionAvoidCars, CarToAvoid) == 608
     && sizeof(AIActionAvoidCars) <= AIACTION_SLOT_SIZE
     && offsetof(AIActionPullOver, MyCreationTime) == 608
     && offsetof(AIActionPullOver, LastDecisionReevaluationTime) == 612
     && offsetof(AIActionPullOver, IsMyDrivingChoiceOkay) == 616
     && offsetof(AIActionPullOver, New620) == 620
     && offsetof(AIActionPullOver, PullOverTimeout) == 624
     && offsetof(AIActionIJustGotHit, CarIHit) == 608
     && sizeof(AIActionIJustGotHit) <= AIACTION_SLOT_SIZE
     && offsetof(AIActionGetUnstuck, MyCreationTime) == 608
     && offsetof(AIActionGetUnstuck, MinimumLifetime) == 612
     && offsetof(AIActionGetUnstuck, MinimumLifetimeInEffect) == 616
     && offsetof(AIActionAvoidRoadBlock, RoadBlockToAvoid) == 608
     && sizeof(AIActionAvoidRoadBlock) <= AIACTION_SLOT_SIZE) ? 1 : -1];
// What follows a car pointer is retail's only where a pointer is 4 bytes.
#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char aiactions_layout_check32[
    (offsetof(AIActionPass, AmountToProjectIntoFuture) == 612
     && offsetof(AIActionPass, MyCreationTime) == 616
     && offsetof(AIActionAvoidCars, SecondsToImpact) == 612
     && offsetof(AIActionAvoidCars, IsMyDrivingChoiceOkay) == 616
     && offsetof(AIActionAvoidCars, LastDecisionReevaluationTime) == 620
     && offsetof(AIActionAvoidCars, MyCreationTime) == 624
     && offsetof(AIActionAvoidCars, MinLifetime) == 628
     && offsetof(AIActionAvoidCars, UsedPreferredSide) == 632
     && offsetof(AIActionIJustGotHit, LastDecisionReevaluationTime)
        == 612) ? 1 : -1];
#endif
#endif

// The demo's tables (retail 0x002b7b10, 0x002b7bd0, 0x002b7b90, 0x002b7b50,
// 0x002b79d0, 0x002b7c10, 0x002b7c50, 0x002b7ad0, 0x002b7a10, 0x002b7a50
// and 0x002b7a90), eight entries each in AIAction's slots.
#define AIJUSTDRIVE_VTABLE         0x0029afa0u
#define AIDRAFT_VTABLE             0x0029b060u
#define AINUDGECAR_VTABLE          0x0029b020u
#define AIBLOCK_VTABLE             0x0029afe0u
#define AIACCIDENTRECOVERY_VTABLE  0x0029ae60u
#define AIPASS_VTABLE              0x0029b0a0u
#define AIAVOIDCARS_VTABLE         0x0029b0e0u
#define AIPULLOVER_VTABLE          0x0029af60u
#define AIIJUSTGOTHIT_VTABLE       0x0029aea0u
#define AIGETUNSTUCK_VTABLE        0x0029aee0u
#define AIAVOIDROADBLOCK_VTABLE    0x0029af20u

// --------------------------------------------------------- JustDrive

// 0x001c73c0, (int score, float timeout). Type JUST_DRIVE, and the
// re-evaluation time 0.
AIActionJustDrive *aijustdrive_init(AIActionJustDrive *a, int32_t score,
                                    float timeout);

// 0x001ca7f8.
void aijustdrive_destroy(AIActionJustDrive *a, int32_t flags);

// 0x001c7458, static. 0.
int32_t aijustdrive_calculate_score(DrivingInformation *info);

// 0x001c7460 and 0x001c74b0. Never.
int aijustdrive_has_been_accomplished(AIActionJustDrive *a,
                                      DrivingInformation *info);
int aijustdrive_has_failed(AIActionJustDrive *a, DrivingInformation *info);

// 0x001c7468. Past the timeout, strictly, and allowed to expire.
int aijustdrive_has_expired(AIActionJustDrive *a, DrivingInformation *info);

// 0x001c74b8. Every three seconds or more, when the choice is not driving
// line 0: line 0 is tried with IsDriveable (with
// AIDriverAvoidCarsImpactTimeThreshold), and when it is driveable it
// becomes the choice and the location's line, and its target the
// action's. Otherwise the choice is made a line (line 0 if it is not one)
// and the target built for it. Then the tolerance 0 and the four flags 1.
void aijustdrive_calculate_points_to_drive(AIActionJustDrive *a,
                                           DrivingInformation *info);

// 0x001ca7e8. "Just Drive".
const char *aijustdrive_get_name(AIActionJustDrive *a);

// ------------------------------------------------------------- Draft

// 0x001c7690, (int score, float timeout). Type DRAFT.
AIActionDraft *aidraft_init(AIActionDraft *a, int32_t score, float timeout);

// 0x001ca918.
void aidraft_destroy(AIActionDraft *a, int32_t flags);

// 0x001c7720, static. 200 when the list has a car just ahead of `car`,
// else -1.
int32_t aidraft_calculate_score(DrivingInformation *info, Car *car);

// 0x001c7750 and 0x001c77a0. Never.
int aidraft_has_been_accomplished(AIActionDraft *a, DrivingInformation *info);
int aidraft_has_failed(AIActionDraft *a, DrivingInformation *info);

// 0x001c7758. As JustDrive's.
int aidraft_has_expired(AIActionDraft *a, DrivingInformation *info);

// 0x001c77a8. The target for the choice, made a line first if it is not
// one; the tolerance 0 and three flags 1. With a car just ahead that
// overlaps the car across and is under 6 m on, the speed is that car's
// less (20 less the gap), when that is under the speed the action has.
void aidraft_calculate_points_to_drive(AIActionDraft *a,
                                       DrivingInformation *info);

// ---------------------------------------------- NudgeCar and Block

// 0x001c8028 and 0x001c8160, (int score, float timeout, Car *car). Type
// NUDGE_CAR or BLOCK, and the car.
AIActionNudgeCar *ainudgecar_init(AIActionNudgeCar *a, int32_t score,
                                  float timeout, Car *car);
AIActionBlock *aiblock_init(AIActionBlock *a, int32_t score, float timeout,
                            Car *car);

// 0x001ca8b8 and 0x001ca858.
void ainudgecar_destroy(AIActionNudgeCar *a, int32_t flags);
void aiblock_destroy(AIActionBlock *a, int32_t flags);

// 0x001c80d8 and 0x001c8210, static. No car, and 300 or 400.
int32_t ainudgecar_calculate_score(DrivingInformation *info, Car **car);
int32_t aiblock_calculate_score(DrivingInformation *info, Car **car);

// 0x001c80e8 and 0x001c8220: always. 0x001c8148 and 0x001c8280: never.
int ainudgecar_has_been_accomplished(AIActionNudgeCar *a,
                                     DrivingInformation *info);
int ainudgecar_has_failed(AIActionNudgeCar *a, DrivingInformation *info);
int aiblock_has_been_accomplished(AIActionBlock *a,
                                  DrivingInformation *info);
int aiblock_has_failed(AIActionBlock *a, DrivingInformation *info);

// 0x001c80f0 and 0x001c8228. Not within the timeout, no points yet, and
// allowed to expire.
int ainudgecar_has_expired(AIActionNudgeCar *a, DrivingInformation *info);
int aiblock_has_expired(AIActionBlock *a, DrivingInformation *info);

// 0x001c8150 and 0x001c8288. PointsToDriveWillExecuteAction 1, and
// nothing else.
void ainudgecar_calculate_points_to_drive(AIActionNudgeCar *a,
                                          DrivingInformation *info);
void aiblock_calculate_points_to_drive(AIActionBlock *a,
                                       DrivingInformation *info);

// -------------------------------------------------- AccidentRecovery

// 0x001ca1f0, (int score, float timeout). Type ACCIDENT_RECOVERY, created
// now (WorldTimer), not reset.
AIActionAccidentRecovery *aiaccidentrecovery_init(AIActionAccidentRecovery *a,
                                                  int32_t score,
                                                  float timeout);

// 0x001ca5c8.
void aiaccidentrecovery_destroy(AIActionAccidentRecovery *a, int32_t flags);

// 0x001ca2a8, static. 500 for a car with under two wheels down that is
// not sort of parallel to the track (0.707), else -1.
int32_t aiaccidentrecovery_calculate_score(DrivingInformation *info);

// 0x001ca2f0, static. Whether the car's up axis, made unit, has a dot
// product with the ground's normal under it (GetElevation) above
// `threshold`.
int aiaccidentrecovery_sort_of_parallel_to_track(Car *car, float threshold);

// 0x001ca398. Reset already, or all four wheels down and sort of
// parallel to the track (0.707).
int aiaccidentrecovery_has_been_accomplished(AIActionAccidentRecovery *a,
                                             DrivingInformation *info);

// 0x001ca430. Never.
int aiaccidentrecovery_has_failed(AIActionAccidentRecovery *a,
                                  DrivingInformation *info);

// 0x001ca3e8. As JustDrive's.
int aiaccidentrecovery_has_expired(AIActionAccidentRecovery *a,
                                   DrivingInformation *info);

// 0x001ca438. The target for the choice, from the location's line when
// the choice is not a line, parallel to the line; a speed of 0 at once,
// no throttle or brake. Five seconds or more after it was made, the car
// is reset once (PleaseResetMeLater).
void aiaccidentrecovery_calculate_points_to_drive(AIActionAccidentRecovery *a,
                                                  DrivingInformation *info);

// 0x001ca5b8. "Accident recovery".
const char *aiaccidentrecovery_get_name(AIActionAccidentRecovery *a);

// -------------------------------------------------------------- Pass

// 0x001c78f8, (int score, float timeout, Car *car, float amount). Type
// PASS, the car to pass, the amount (which nothing reads) and created
// now.
AIActionPass *aipass_init(AIActionPass *a, int32_t score, float timeout,
                          Car *car, float amount);

// 0x001ca988.
void aipass_destroy(AIActionPass *a, int32_t flags);

// 0x001c79d8, static. -1 in the grace period. Else the cars before mine in
// the list, in order: one ahead, less than twice as far across as on,
// that CanICatchThisCar says can be caught, is tried with
// TryToDriveAroundCar (AIActionPassMaxTimeAheadToMakeAttempt) from the
// information's choice into `choice`; the first that drives round it on
// a side SideOfCarIsOkay allows is `*car`, and 300. Else -1. `choice` is
// left as the last try left it. The float is not read.
int32_t aipass_calculate_score(DrivingInformation *info, Car **car,
                               DrivingChoice *choice, float *unused);

// 0x001c7e28, static. A traffic car, one no faster than
// TryToDriveAroundCarMinSpeedForDrivingLine, a line, or the preferred
// side.
int aipass_side_of_car_is_okay(NearbyCar *nc, DrivingChoice *choice,
                               int preferred);

// 0x001c7b90. When the list's first car is not the car to pass, the score
// again, and a new choice it found becomes the information's, with its
// car and a new creation time. Then, three seconds or more after that,
// done when the car is off the list or more than ten metres past the two
// half lengths behind. Done sets the location's relaxed switch.
int aipass_has_been_accomplished(AIActionPass *a, DrivingInformation *info);

// 0x001c7d48. The car is off the list, or, under three seconds on, ahead
// and out of reach (CanICatchThisCar). Failing sets the relaxed switch.
int aipass_has_failed(AIActionPass *a, DrivingInformation *info);

// 0x001c7d00. As JustDrive's.
int aipass_has_expired(AIActionPass *a, DrivingInformation *info);

// 0x001c7ea8. Boost, throttle and brake, and the target from scratch: round
// the car while it is ahead (TryToDriveAroundCar), the choice's line
// parallel to it with IsDriveable once it is not, both at the line's
// speed. With the car off the list, the line built parallel and the
// points not the action's.
void aipass_calculate_points_to_drive(AIActionPass *a,
                                      DrivingInformation *info);

// 0x001ca978. "Pass".
const char *aipass_get_name(AIActionPass *a);

// --------------------------------------------------------- AvoidCars

// 0x001c6ba0, (int score, float timeout, Car *car, float secs, bool okay,
// bool usedPreferred). Type AVOID_CARS, the car, the seconds to the hit,
// the two flags, created and re-evaluated now, and MinLifetime two
// seconds past the hit.
AIActionAvoidCars *aiavoidcars_init(AIActionAvoidCars *a, int32_t score,
                                    float timeout, Car *car, float secs,
                                    int okay, int usedPreferred);

// 0x001caa00.
void aiavoidcars_destroy(AIActionAvoidCars *a, int32_t flags);

// 0x001c6cf8, static. The car my own target runs into first
// (WhoWillThisDriveTargetHit), when that is under
// AIDriverAvoidCarsImpactTimeThreshold: `*car`, `*secs`, the information's
// choice into `choice` and 400. In the grace period, a car that is no
// player's is let be (`*okay` 1); else MakeNewChoice makes the choice,
// `*okay` its answer. Otherwise -1, `*secs` 99999 and the flags 0.
int32_t aiavoidcars_calculate_score(DrivingInformation *info, Car **car,
                                    DrivingChoice *choice, float *secs,
                                    int *okay, int *usedPreferred);

// 0x001c6e78. Past MinLifetime; sets the relaxed switch.
int aiavoidcars_has_been_accomplished(AIActionAvoidCars *a,
                                      DrivingInformation *info);

// 0x001c6ef0 and 0x001c6ee8. Never.
int aiavoidcars_has_failed(AIActionAvoidCars *a, DrivingInformation *info);
int aiavoidcars_has_expired(AIActionAvoidCars *a, DrivingInformation *info);

// 0x001c6ef8. My own target, at the line's speed. Every 0.3 s or more (out
// of the grace period, or avoiding a player's car) the choice is made
// again with MakeNewChoice, from a side of the car when both are slow and
// the choice is a line; a line it lands on becomes the location's, and is
// highlighted. A choice not just made, or made with no points, is checked
// with IsDriveable, from the location's line when it is not valid. With
// no good choice and a car we care about close ahead, not blinking, the
// speed is that car's less 0.1 (or the line's when both are slow), and no
// less than 20 behind traffic or a cop.
void aiavoidcars_calculate_points_to_drive(AIActionAvoidCars *a,
                                           DrivingInformation *info);

// 0x001ca9f0. "Avoid Cars".
const char *aiavoidcars_get_name(AIActionAvoidCars *a);

// 0x001ca9e8.
Car *aiavoidcars_get_car_to_avoid(AIActionAvoidCars *a);

// --------------------------------------------------------- PullOver

// 0x001c8298, (int score, float timeout, float pullOverTimeout,
// NearbyCarList *list, DrivingLocation *loc). Type PULL_OVER, created now,
// re-evaluated at 0, the choice okay, and New620 whether the room to the
// right edge at loc's point is over 2 m (1 when either pointer is NULL).
// PointsToDrive is cleared. The callers pass the controller's list and
// location; the DoSnapshot passes NULLs.
AIActionPullOver *aipullover_init(AIActionPullOver *a, int32_t score,
                                  float timeout, float pullOverTimeout,
                                  NearbyCarList *list,
                                  DrivingLocation *loc);

// 0x001ca788.
void aipullover_destroy(AIActionPullOver *a, int32_t flags);

// 0x001c8400, static. Only for a traffic car: 600 within 150 m of the
// chopper while its plan is 0 to 2 or 4, or of a cop (not disabled) or a
// player whose car's CopLights word is set, within three and a half
// times that car's speed and no less than 100 m. Otherwise -1.
int32_t aipullover_calculate_score(DrivingInformation *info);

// 0x001c8610. A traffic car whose score is -1.
int aipullover_has_been_accomplished(AIActionPullOver *a,
                                     DrivingInformation *info);

// 0x001c8658 and 0x001c8650. Never.
int aipullover_has_failed(AIActionPullOver *a, DrivingInformation *info);
int aipullover_has_expired(AIActionPullOver *a, DrivingInformation *info);

// 0x001c86a8. My own target, no boost. Until PullOverTimeout (none at
// -999): every 0.3 s, or with no points, the route ahead edging to the
// right side of the track (a driver of skill -2 keeps to the choice's
// line), and round a car it hits under 2 s with MakeNewChoice. A skill -2
// driver slows at 12% (20% with no way round) of its most deceleration;
// any other stops hard with no location or no way round, or when over 15
// m/s or within 2 m of the edge, else holds 14 m/s until there. Under 0.5
// m/s, or touching another car, it stops. Past the timeout, the
// location's line at a stop.
void aipullover_calculate_points_to_drive(AIActionPullOver *a,
                                          DrivingInformation *info);

// 0x001ca778. "Pull over".
const char *aipullover_get_name(AIActionPullOver *a);

// ------------------------------------------------------- IJustGotHit

// 0x001c9c68, (int score, float timeout, Car *car). Type I_JUST_GOT_HIT,
// the car, and the re-evaluation time 0.
AIActionIJustGotHit *aijustgothit_init(AIActionIJustGotHit *a, int32_t score,
                                       float timeout, Car *car);

// 0x001ca638.
void aijustgothit_destroy(AIActionIJustGotHit *a, int32_t flags);

// 0x001c9d20, static. Of my body's two-car collisions with a car on the
// list, the one to answer (see the source), into `*car`, and 400; -1 and
// `*car` NULL for none.
int32_t aijustgothit_calculate_score(DrivingInformation *info, Car **car);

// 0x001c9e90. No two-car collision on the list now, or the car hit off
// it. A collision now makes its car CarIHit.
int aijustgothit_has_been_accomplished(AIActionIJustGotHit *a,
                                       DrivingInformation *info);

// 0x001c9f58. Never.
int aijustgothit_has_failed(AIActionIJustGotHit *a, DrivingInformation *info);

// 0x001c9f10. As JustDrive's.
int aijustgothit_has_expired(AIActionIJustGotHit *a,
                             DrivingInformation *info);

// 0x001c9f60. My own target, a new choice (MakeNewChoice) every 0.2 s or
// with no points. Heading off the road forwards, it brakes; else the speed
// depends on where the car hit is (see the source), at no less than 20
// m/s when not at the line's speed.
void aijustgothit_calculate_points_to_drive(AIActionIJustGotHit *a,
                                            DrivingInformation *info);

// 0x001ca628. "I just got hit!".
const char *aijustgothit_get_name(AIActionIJustGotHit *a);

// -------------------------------------------------------- GetUnstuck

// 0x001c8b30, (int score, float timeout, float minLifetime). Type
// GET_UNSTUCK, created now, and the minimum lifetime in effect unless it
// is -1, give or take 0.001.
AIActionGetUnstuck *aigetunstuck_init(AIActionGetUnstuck *a, int32_t score,
                                      float timeout, float minLifetime);

// 0x001ca6a8.
void aigetunstuck_destroy(AIActionGetUnstuck *a, int32_t flags);

// 0x001c8c30, static. -1 in the grace period, with the location clear or
// fewer than three wheels down. Stuck when the car is 20 m or more past an
// edge of its route point; or, as an AI car at 25 m/s or less or traffic
// at 20 or less, heading out of the route forwards; or stuck behind
// someone; or with a collision in front 0.4 s old or more while going
// under 1 m/s (1.001, give or take). Stuck asks the controller's
// FindWhereIAm, and scores 500.
int32_t aigetunstuck_calculate_score(DrivingInformation *info);

// 0x001c8ee8, static. Not blinking, at 15 m/s or less, and a car on the
// list that is not mine, at AISlowCarSpeed or less either way, overlapping
// mine across and within 9 m ahead past the two half lengths. `loc` is
// not read.
int aigetunstuck_are_we_stuck_behind_someone(DrivingLocation *loc,
                                             NearbyCarList *list);

// 0x001c9140. Past the minimum lifetime, facing within 0.98 of the goal
// point (three points on along the line) and not stuck behind someone.
// Done asks FindWhereIAm and the driver's ClearSteeringMemory.
int aigetunstuck_has_been_accomplished(AIActionGetUnstuck *a,
                                       DrivingInformation *info);

// 0x001c9340. The location clear or fewer than three wheels down; else,
// past the minimum lifetime, heading out of the route backwards, or a
// collision behind 0.4 s old or more while going under 1 m/s either way.
// Failing asks FindWhereIAm and ClearSteeringMemory.
int aigetunstuck_has_failed(AIActionGetUnstuck *a, DrivingInformation *info);

// 0x001c9298. As JustDrive's, and expiring asks FindWhereIAm and
// ClearSteeringMemory.
int aigetunstuck_has_expired(AIActionGetUnstuck *a, DrivingInformation *info);

// 0x001c9550. The goal point, then the route ahead parallel to the line,
// backwards: -15 m/s for an AI car, -6 for any other. With the location
// clear, no points and not the action's.
void aigetunstuck_calculate_points_to_drive(AIActionGetUnstuck *a,
                                            DrivingInformation *info);

// 0x001ca698. "Get Unstuck".
const char *aigetunstuck_get_name(AIActionGetUnstuck *a);

// ---------------------------------------------------- AvoidRoadBlock

// 0x001c9668, (int score, float timeout, const tRoadBlock *rb). Type
// AVOID_ROADBLOCK and the roadblock.
AIActionAvoidRoadBlock *aiavoidroadblock_init(AIActionAvoidRoadBlock *a,
                                              int32_t score, float timeout,
                                              const tRoadBlock *rb);

// 0x001ca718.
void aiavoidroadblock_destroy(AIActionAvoidRoadBlock *a, int32_t flags);

// 0x001c9718, static. The first active roadblock with a cop that is more
// than my speed times 2.5 s (and no less than 100 m) ahead round the
// track: `*rb`, and 600. Otherwise -1 and `*rb` NULL.
int32_t aiavoidroadblock_calculate_score(DrivingInformation *info,
                                         const tRoadBlock **rb);

// 0x001c9858. Both cops gone, or the roadblock more than 15 m behind.
int aiavoidroadblock_has_been_accomplished(AIActionAvoidRoadBlock *a,
                                           DrivingInformation *info);

// 0x001c98d8 and 0x001c98d0. Never.
int aiavoidroadblock_has_failed(AIActionAvoidRoadBlock *a,
                                DrivingInformation *info);
int aiavoidroadblock_has_expired(AIActionAvoidRoadBlock *a,
                                 DrivingInformation *info);

// 0x001c98e0. The route up to the roadblock's point (on its route), the
// one ahead nearest the escape lane (within 5 m of the road), or the
// route's last, edging from my offset off the line to the escape lane's
// (my own past the road), then parallel, at the line's speed. Behind a
// racer it would hit within a second, the speed is that car's less 0.1,
// and no less than 30.
void aiavoidroadblock_calculate_points_to_drive(AIActionAvoidRoadBlock *a,
                                                DrivingInformation *info);

// 0x001ca708. "Avoid Roadblock".
const char *aiavoidroadblock_get_name(AIActionAvoidRoadBlock *a);

// Installs the eleven tables. The DoSnapshots are NULL.
void aiactions_install_vtables(void);

#endif
