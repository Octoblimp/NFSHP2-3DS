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
// Their GetNames and destructors are 0x001ca5b8 to 0x001ca974. Pass,
// AvoidCars, PullOver, GetUnstuck, AvoidRoadBlock and IJustGotHit are
// 11d-2's and 11d-3's. The DoSnapshots wait on ReplaySnapshot.
//
// Checked against retail by tools/drivingchoice_check.py. Written up in
// docs/formats/ai-action.md.
#ifndef AIACTIONS_H
#define AIACTIONS_H

#include <stddef.h>
#include <stdint.h>

#include "aiaction.h"
#include "car.h"
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

#ifndef AIACTION_NO_ASSERT
typedef char aiactions_layout_check[
    (offsetof(AIActionJustDrive, LastDecisionReevaluationTime) == 608
     && offsetof(AIActionNudgeCar, CarToNudge) == 608
     && offsetof(AIActionBlock, CarToBlock) == 608
     && offsetof(AIActionAccidentRecovery, MyCreationTime) == 608
     && offsetof(AIActionAccidentRecovery, HaveResetYet) == 612
     && sizeof(AIActionAccidentRecovery) <= AIACTION_SLOT_SIZE) ? 1 : -1];
#endif

// The demo's tables (retail 0x002b7b10, 0x002b7bd0, 0x002b7b90, 0x002b7b50
// and 0x002b79d0), eight entries each in AIAction's slots.
#define AIJUSTDRIVE_VTABLE         0x0029afa0u
#define AIDRAFT_VTABLE             0x0029b060u
#define AINUDGECAR_VTABLE          0x0029b020u
#define AIBLOCK_VTABLE             0x0029afe0u
#define AIACCIDENTRECOVERY_VTABLE  0x0029ae60u

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

// Installs the five tables. The DoSnapshots are NULL.
void aiactions_install_vtables(void);

#endif
