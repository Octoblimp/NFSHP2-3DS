// aiactions -- see aiactions.h.
//
// Written from retail's listing. Every float expression keeps the image's
// association.

#include "aiactions.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "carcollisionpredict.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "cartypeinfo.h"
#include "chopper.h"
#include "collision.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "player.h"
#include "race.h"
#include "racecore.h"
#include "realtime.h"   // WorldTimer
#include "replay.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// Retail's constants: AIAction.obj's .lit4 and the few built with `lui`.
#define AIA_TICKS_TO_SECONDS   0.000250000012f  // gp-28708 and the rest
#define AIJD_REEVALUATE_EVERY  3.0f             // lui 0x4040
#define AIJD_NO_HIT            99999.0f         // gp-28700
#define AIDR_CLOSE             6.0f             // lui 0x40c0
#define AIDR_GAP               20.0f            // lui 0x41a0
#define AIAR_UPRIGHT           0.707000017f     // gp-28544, gp-28540
#define AIAR_RESET_AFTER       5.0f             // lui 0x40a0
#define AIPA_SETTLE            3.0f             // lui 0x4040, twice
#define AIPA_BEHIND            10.0f            // lui 0x4120
#define AIPA_NO_HIT            99999.0f         // gp-28680
#define AIAC_NO_HIT            99999.0f         // gp-28736, gp-28720
#define AIAC_MIN_LIFETIME      2.0f             // lui 0x4000
#define AIAC_REEVALUATE_EVERY  0.300000012f     // gp-28724
#define AIAC_SLOW_ME           10.0f            // lui 0x4120
#define AIAC_SLOW_IT           5.0f             // lui 0x40a0
#define AIAC_LOOK_AHEAD        0.100000001f     // gp-28716
#define AIAC_HALF              0.5f             // lui 0x3f00
#define AIAC_ACROSS_MARGIN     1.0f             // lui 0x3f80
#define AIAC_SLOWER_BY         0.100000001f     // gp-28712
#define AIAC_MIN_SPEED_BEHIND  20.0f            // lui 0x41a0
#define AIPO_CHOPPER_RANGE     150.0f           // lui 0x4316
#define AIPO_LIGHTS_SECONDS    3.5f             // lui 0x4060
#define AIPO_LIGHTS_MIN        100.0f           // lui 0x42c8
#define AIPO_NO_TIMEOUT        (-999.0f)        // gp-28668
#define AIPO_TIMEOUT_EPSILON   0.00100000005f   // gp-28664
#define AIPO_REEVALUATE_EVERY  0.300000012f     // gp-28652
#define AIPO_HIT_SOON          2.0f             // lui 0x4000
#define AIPO_GENTLE            0.120000005f     // gp-28648
#define AIPO_FIRM              0.200000003f     // gp-28644
#define AIPO_BRAKE             0.200000003f     // gp-28640, gp-28636
#define AIPO_TOO_FAST          15.0f            // lui 0x4170
#define AIPO_ROOM_LOW          2.0f             // lui 0x4000
#define AIPO_ROOM_HIGH         4.0f             // lui 0x4080
#define AIPO_CREEP_SPEED       14.0f            // lui 0x4160
#define AIPO_TOLERANCE         2.0f             // lui 0x4000
#define AIPO_STOPPED           0.5f             // lui 0x3f00
#define AIPO_TIME_TO_SPEED     0.200000003f     // gp-28632
#define AIPO_CAREFUL_SKILL     (-2)
#define AIIJ_REEVALUATE_EVERY  0.200000003f     // gp-28572
#define AIIJ_BRAKE             0.200000003f     // gp-28568
#define AIIJ_OVERLAP           2.79999995f      // gp-28564
#define AIIJ_BACK_OFF          6.0f             // lui 0x40c0
#define AIIJ_ACCEL             0.200000003f     // gp-28560, gp-28548
#define AIIJ_SLOWER_BY         0.100000001f     // gp-28556
#define AIIJ_SLOWER_UNUSED     0.200000003f     // gp-28552
#define AIIJ_MIN_SPEED         20.0f            // lui 0x41a0
#define AIGU_NO_LIFETIME       (-1.0f)          // lui 0xbf80
#define AIGU_LIFETIME_EPSILON  0.00100000005f   // gp-28628
#define AIGU_OFF_ROAD          20.0f            // lui 0x41a0
#define AIGU_SLOW_AI           25.0f            // lui 0x41c8
#define AIGU_SLOW_TRAFFIC      20.0f            // lui 0x41a0
#define AIGU_HIT_AGO           0.400000006f     // gp-28620, gp-28592
#define AIGU_STOPPED           1.0f             // lui 0x3f80
#define AIGU_STOPPED_EPSILON   0.00100000005f   // gp-28616, gp-28588
#define AIGU_BEHIND_GAP        9.0f             // lui 0x4110
#define AIGU_FACING            0.980000019f     // gp-28608
#define AIGU_REVERSE_AI        (-15.0f)         // lui 0xc170, twice
#define AIGU_REVERSE           (-6.0f)          // lui 0xc0c0
#define AIGU_GOAL_AHEAD        3                // route points
#define AIRB_LOOK_SECONDS      2.5f             // lui 0x4020
#define AIRB_LOOK_MIN          100.0f           // lui 0x42c8
#define AIRB_PASSED            15.0f            // lui 0x4170
#define AIRB_ON_ROAD           5.0f             // lui 0x40a0
#define AIRB_HIT_WITHIN        1.0f             // lui 0x3f80
#define AIRB_SLOWER_BY         0.100000001f     // gp-28584
#define AIRB_MIN_SPEED         30.0f            // lui 0x41f0

#define AIDR_SCORE   200
#define AINC_SCORE   300
#define AIPA_SCORE   300
#define AIBL_SCORE   400
#define AIAC_SCORE   400
#define AIIJ_SCORE   400
#define AIAR_SCORE   500
#define AIGU_SCORE   500
#define AIPO_SCORE   600
#define AIRB_SCORE   600
#define AIA_NO_SCORE (-1)

float AIDriverAvoidCarsImpactTimeThreshold = 2.0f;

// `max.s`, as aiaction.c has it.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// Seconds since `t`: `WorldTimer - t` as a signed word, converted, times
// the tick.
static float seconds_since(const Timer *t)
{
    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)
           * AIA_TICKS_TO_SECONDS;
}

// JustDrive's, Draft's and AccidentRecovery's HasExpired, the same code
// three times: `c.lt.s` DeltaTime against the seconds, then CanExpire.
static int past_timeout(const AIPlan *p)
{
    return p->DeltaTime < seconds_since(&p->ExpiryTimer)
           && p->CanExpire != 0;
}

// NudgeCar's and Block's: `c.le.s` the other way round, so a NaN goes on
// to the tests, and no points yet.
static int past_timeout_unstarted(const AIAction *a)
{
    if (seconds_since(&a->Base.ExpiryTimer) <= a->Base.DeltaTime)
        return 0;
    if (a->PointsToDriveWillExecuteAction != 0)
        return 0;
    return a->Base.CanExpire != 0;
}

// The five destructors: the vptr, AIAction's with 0, and the pool's free
// when flags & 1.
static void destroy_as(AIAction *a, uint32_t vtable, int32_t flags)
{
    a->Base._vtable = vtable;
    aiaction_destroy(a, 0);
    if (flags & 1)
        aiaction_delete(a);
}

// Driving line 0 as the choice and the location's line, when the choice is
// not a line already: JustDrive's and Draft's.
static void make_choice_a_line(DrivingInformation *info)
{
    DrivingChoice *choice = &info->MyDrivingChoice;

    if (drivingchoice_type_is_driving_line(choice->Type))
        return;
    drivingchoice_set_choice(choice, CHOICE_DRIVING_LINE_0, NULL, 0);
    drivinglocation_set_driving_line(
        &info->MyDrivingLocation,
        drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,
                                       info->MyNearbyCarList.MyCar),
        1);
}

// --------------------------------------------------------- JustDrive

AIActionJustDrive *aijustdrive_init(AIActionJustDrive *a, int32_t score,
                                    float timeout)
{
    // 0x001c73c0.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_JUST_DRIVE;
    a->Base.Base._vtable = AIJUSTDRIVE_VTABLE;
    a->LastDecisionReevaluationTime.PackedTime = 0;
    return a;
}

void aijustdrive_destroy(AIActionJustDrive *a, int32_t flags)
{
    // 0x001ca7f8.
    destroy_as(&a->Base, AIJUSTDRIVE_VTABLE, flags);
}

int32_t aijustdrive_calculate_score(DrivingInformation *info)
{
    // 0x001c7458.
    (void)info;
    return 0;
}

int aijustdrive_has_been_accomplished(AIActionJustDrive *a,
                                      DrivingInformation *info)
{
    // 0x001c7460.
    (void)a;
    (void)info;
    return 0;
}

int aijustdrive_has_failed(AIActionJustDrive *a, DrivingInformation *info)
{
    // 0x001c74b0.
    (void)a;
    (void)info;
    return 0;
}

int aijustdrive_has_expired(AIActionJustDrive *a, DrivingInformation *info)
{
    // 0x001c7468.
    (void)info;
    return past_timeout(&a->Base.Base);
}

void aijustdrive_calculate_points_to_drive(AIActionJustDrive *a,
                                           DrivingInformation *info)
{
    // 0x001c74b8. The time is stored whenever three seconds have gone,
    // in the delay slot of the test of the choice, so a car already on
    // line 0 restarts the wait too.
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    int32_t now = WorldTimer;
    int done = 0;

    if (AIJD_REEVALUATE_EVERY
        <= (float)(int32_t)((uint32_t)now
                            - a->LastDecisionReevaluationTime.PackedTime)
           * AIA_TICKS_TO_SECONDS) {
        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)now;
        if (choice->Type != CHOICE_DRIVING_LINE_0) {
            DriveTarget t;
            DrivingChoice c;
            float score, hitTime = AIJD_NO_HIT;
            Car *hitCar = NULL;

            drivetarget_init(&t);
            drivingchoice_set_choice(&c, CHOICE_DRIVING_LINE_0, NULL, 0);
            if (drivingchoice_is_driveable(
                    &c, &t, 0, &score, &hitCar, &hitTime, loc,
                    &info->MyNearbyCarList, 0.0f,
                    AIDriverAvoidCarsImpactTimeThreshold, 0.0f,
                    MOVEMENT_TOWARDS_LINE)) {
                *choice = c;
                done = 1;
                drivinglocation_set_driving_line(
                    loc,
                    drivingchoice_get_driving_line(
                        CHOICE_DRIVING_LINE_0, info->MyNearbyCarList.MyCar),
                    1);
                drivetarget_assign(&a->Base.PointsToDrive, &t);
            }
            drivetarget_destroy(&t);
        }
    }
    if (!done) {
        make_choice_a_line(info);
        drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive, loc,
                                         &info->MyNearbyCarList, 0.0f, 0.0f,
                                         MOVEMENT_TOWARDS_LINE);
    }
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.PointsToDriveWillExecuteAction = 1;
    a->Base.UseDrivingLineSpeed = 1;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.AllowedToUseBoost = 1;
}

const char *aijustdrive_get_name(AIActionJustDrive *a)
{
    // 0x001ca7e8.
    (void)a;
    return "Just Drive";
}

// ------------------------------------------------------------- Draft

AIActionDraft *aidraft_init(AIActionDraft *a, int32_t score, float timeout)
{
    // 0x001c7690.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_DRAFT;
    a->Base.Base._vtable = AIDRAFT_VTABLE;
    return a;
}

void aidraft_destroy(AIActionDraft *a, int32_t flags)
{
    // 0x001ca918.
    destroy_as(&a->Base, AIDRAFT_VTABLE, flags);
}

int32_t aidraft_calculate_score(DrivingInformation *info, Car *car)
{
    // 0x001c7720.
    return nearbycarlist_get_car_ahead(&info->MyNearbyCarList, car) != NULL
               ? AIDR_SCORE
               : AIA_NO_SCORE;
}

int aidraft_has_been_accomplished(AIActionDraft *a, DrivingInformation *info)
{
    // 0x001c7750.
    (void)a;
    (void)info;
    return 0;
}

int aidraft_has_failed(AIActionDraft *a, DrivingInformation *info)
{
    // 0x001c77a0.
    (void)a;
    (void)info;
    return 0;
}

int aidraft_has_expired(AIActionDraft *a, DrivingInformation *info)
{
    // 0x001c7758.
    (void)info;
    return past_timeout(&a->Base.Base);
}

void aidraft_calculate_points_to_drive(AIActionDraft *a,
                                       DrivingInformation *info)
{
    // 0x001c77a8. The speed is only ever lowered: the action's own, 0
    // from the constructor, is what it must beat.
    NearbyCarList *list = &info->MyNearbyCarList;
    NearbyCar *nc;

    make_choice_a_line(info);
    drivingchoice_build_drive_target(&info->MyDrivingChoice,
                                     &a->Base.PointsToDrive,
                                     &info->MyDrivingLocation, list, 0.0f,
                                     0.0f, MOVEMENT_TOWARDS_LINE);
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.AllowedToUseBoost = 1;
    a->Base.UseDrivingLineSpeed = 1;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    nc = nearbycarlist_get_car_ahead(list, list->MyCar);
    if (nc != NULL
        && fabsf(nc->Position.x) < list->MyHalfSizeL + nc->ApparentHalfSizeL
        && nc->Position.y < AIDR_CLOSE) {
        float speed = nc->TheCar->State.VelocityMagnitude
                      - (AIDR_GAP - nc->Position.y);

        if (speed < a->Base.DesiredSpeed) {
            a->Base.DesiredSpeed = speed;
            a->Base.TimeToGetToDesiredSpeed = 0.0f;
            a->Base.UseDrivingLineSpeed = 0;
        }
    }
    a->Base.PointsToDriveWillExecuteAction = 1;
}

// ---------------------------------------------- NudgeCar and Block

AIActionNudgeCar *ainudgecar_init(AIActionNudgeCar *a, int32_t score,
                                  float timeout, Car *car)
{
    // 0x001c8028.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_NUDGE_CAR;
    a->CarToNudge = car;
    a->Base.Base._vtable = AINUDGECAR_VTABLE;
    return a;
}

AIActionBlock *aiblock_init(AIActionBlock *a, int32_t score, float timeout,
                            Car *car)
{
    // 0x001c8160.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_BLOCK;
    a->CarToBlock = car;
    a->Base.Base._vtable = AIBLOCK_VTABLE;
    return a;
}

void ainudgecar_destroy(AIActionNudgeCar *a, int32_t flags)
{
    // 0x001ca8b8.
    destroy_as(&a->Base, AINUDGECAR_VTABLE, flags);
}

void aiblock_destroy(AIActionBlock *a, int32_t flags)
{
    // 0x001ca858.
    destroy_as(&a->Base, AIBLOCK_VTABLE, flags);
}

int32_t ainudgecar_calculate_score(DrivingInformation *info, Car **car)
{
    // 0x001c80d8.
    (void)info;
    *car = NULL;
    return AINC_SCORE;
}

int32_t aiblock_calculate_score(DrivingInformation *info, Car **car)
{
    // 0x001c8210.
    (void)info;
    *car = NULL;
    return AIBL_SCORE;
}

int ainudgecar_has_been_accomplished(AIActionNudgeCar *a,
                                     DrivingInformation *info)
{
    // 0x001c80e8.
    (void)a;
    (void)info;
    return 1;
}

int ainudgecar_has_failed(AIActionNudgeCar *a, DrivingInformation *info)
{
    // 0x001c8148.
    (void)a;
    (void)info;
    return 0;
}

int aiblock_has_been_accomplished(AIActionBlock *a, DrivingInformation *info)
{
    // 0x001c8220.
    (void)a;
    (void)info;
    return 1;
}

int aiblock_has_failed(AIActionBlock *a, DrivingInformation *info)
{
    // 0x001c8280.
    (void)a;
    (void)info;
    return 0;
}

int ainudgecar_has_expired(AIActionNudgeCar *a, DrivingInformation *info)
{
    // 0x001c80f0.
    (void)info;
    return past_timeout_unstarted(&a->Base);
}

int aiblock_has_expired(AIActionBlock *a, DrivingInformation *info)
{
    // 0x001c8228.
    (void)info;
    return past_timeout_unstarted(&a->Base);
}

void ainudgecar_calculate_points_to_drive(AIActionNudgeCar *a,
                                          DrivingInformation *info)
{
    // 0x001c8150.
    (void)info;
    a->Base.PointsToDriveWillExecuteAction = 1;
}

void aiblock_calculate_points_to_drive(AIActionBlock *a,
                                       DrivingInformation *info)
{
    // 0x001c8288.
    (void)info;
    a->Base.PointsToDriveWillExecuteAction = 1;
}

// -------------------------------------------------- AccidentRecovery

AIActionAccidentRecovery *aiaccidentrecovery_init(AIActionAccidentRecovery *a,
                                                  int32_t score,
                                                  float timeout)
{
    // 0x001ca1f0. MyCreationTime's own constructor zeroes it first.
    aiaction_init(&a->Base, score, timeout);
    a->MyCreationTime.PackedTime = 0;
    a->Base.Base._vtable = AIACCIDENTRECOVERY_VTABLE;
    a->Base.Type = AIACTION_ACCIDENT_RECOVERY;
    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
    a->HaveResetYet = 0;
    return a;
}

void aiaccidentrecovery_destroy(AIActionAccidentRecovery *a, int32_t flags)
{
    // 0x001ca5c8.
    destroy_as(&a->Base, AIACCIDENTRECOVERY_VTABLE, flags);
}

int32_t aiaccidentrecovery_calculate_score(DrivingInformation *info)
{
    // 0x001ca2a8. `slti` 2, signed.
    Car *car = info->MyNearbyCarList.MyCar;
    int crashed = 0;

    if (car->State.nWheelsTouchingGround < 2)
        crashed = !aiaccidentrecovery_sort_of_parallel_to_track(car,
                                                                AIAR_UPRIGHT);
    return crashed ? AIAR_SCORE : AIA_NO_SCORE;
}

int aiaccidentrecovery_sort_of_parallel_to_track(Car *car, float threshold)
{
    // 0x001ca2f0. An inline VU0 normalise of BodyMatrix's z axis, all four
    // lanes by `vrsqrt`'s quotient, then a three-lane dot with the normal
    // GetElevation answers. The terrain is asked for and not read.
    const bVector4 *up = &car->State.BodyMatrix.v2;
    int32_t terrain;
    bVector3 normal;
    float q, ux, uy, uz;

    topology_get_elevation(&car->TheTopologyCoordinate, &car->State.Position,
                           &terrain, &normal, NULL);
    q = 1.0f / sqrtf((up->x * up->x + up->y * up->y) + up->z * up->z);
    ux = up->x * q;
    uy = up->y * q;
    uz = up->z * q;
    return threshold < (ux * normal.x + uy * normal.y) + uz * normal.z;
}

int aiaccidentrecovery_has_been_accomplished(AIActionAccidentRecovery *a,
                                             DrivingInformation *info)
{
    // 0x001ca398.
    Car *car;

    if (a->HaveResetYet != 0)
        return 1;
    car = info->MyNearbyCarList.MyCar;
    if (car->State.nWheelsTouchingGround != 4)
        return 0;
    return aiaccidentrecovery_sort_of_parallel_to_track(car, AIAR_UPRIGHT)
           != 0;
}

int aiaccidentrecovery_has_failed(AIActionAccidentRecovery *a,
                                  DrivingInformation *info)
{
    // 0x001ca430.
    (void)a;
    (void)info;
    return 0;
}

int aiaccidentrecovery_has_expired(AIActionAccidentRecovery *a,
                                   DrivingInformation *info)
{
    // 0x001ca3e8.
    (void)info;
    return past_timeout(&a->Base.Base);
}

void aiaccidentrecovery_calculate_points_to_drive(AIActionAccidentRecovery *a,
                                                  DrivingInformation *info)
{
    // 0x001ca438. BuildDriveTarget's answer is not read.
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;

    if (!drivingchoice_type_is_driving_line(choice->Type))
        drivingchoice_set_choice_location(choice, loc);
    drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive, loc,
                                     &info->MyNearbyCarList, 0.0f, 0.0f,
                                     MOVEMENT_PARALLEL_TO_LINE);
    a->Base.TimeToGetToDesiredSpeed = 0.0f;
    a->Base.UseDrivingLineSpeed = 0;
    a->Base.DesiredSpeed = 0.0f;
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.PointsToDriveWillExecuteAction = 1;
    a->Base.AllowedToUseThrottleAndBrake = 0;
    if (AIAR_RESET_AFTER <= seconds_since(&a->MyCreationTime)
        && a->HaveResetYet == 0) {
        car_please_reset_me_later(info->MyNearbyCarList.MyCar);
        a->HaveResetYet = 1;
    }
}

const char *aiaccidentrecovery_get_name(AIActionAccidentRecovery *a)
{
    // 0x001ca5b8.
    (void)a;
    return "Accident recovery";
}

// -------------------------------------------------------------- Pass

AIActionPass *aipass_init(AIActionPass *a, int32_t score, float timeout,
                          Car *car, float amount)
{
    // 0x001c78f8. MyCreationTime's own constructor zeroes it first.
    aiaction_init(&a->Base, score, timeout);
    a->MyCreationTime.PackedTime = 0;
    a->AmountToProjectIntoFuture = amount;
    a->CarToPass = car;
    a->Base.Base._vtable = AIPASS_VTABLE;
    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
    a->Base.Type = AIACTION_PASS;
    return a;
}

void aipass_destroy(AIActionPass *a, int32_t flags)
{
    // 0x001ca988.
    destroy_as(&a->Base, AIPASS_VTABLE, flags);
}

int32_t aipass_calculate_score(DrivingInformation *info, Car **car,
                               DrivingChoice *choice, float *unused)
{
    // 0x001c79d8. Retail leaves f14 stale for TryToDriveAroundCar, which
    // does not read it, and asks CalculateMaxAcceleration for a figure
    // CanICatchThisCar does not read either.
    NearbyCarList *list = &info->MyNearbyCarList;
    Car *me = list->MyCar;
    float maxAccel;
    int32_t n, i;
    int found = 0;

    (void)unused;
    if (race_grace_period_is_active(pCurrentRace, me))
        return AIA_NO_SCORE;
    maxAccel = ai_calculate_max_acceleration(me, me->State.VelocityMagnitude);
    n = nearbycarlist_get_cars_index_in_array(list, me);
    for (i = 0; i < n && !found; i++) {
        NearbyCar *nc = &list->Array[i];
        DriveTarget t;
        int preferred = 0;

        if (!(0.0f < nc->Position.y)
            || !(nc->Position.x < nc->Position.y + nc->Position.y)
            || !ai_can_i_catch_this_car(nc, me, maxAccel, 1))
            continue;
        drivetarget_init(&t);
        *choice = info->MyDrivingChoice;
        if (drivingchoice_try_to_drive_around_car(
                choice, &t, &preferred, nc, &info->MyDrivingLocation, list,
                0.0f, AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, 1)
            && aipass_side_of_car_is_okay(nc, choice, preferred)) {
            *car = nc->TheCar;
            found = 1;
        }
        drivetarget_destroy(&t);
    }
    return found ? AIPA_SCORE : AIA_NO_SCORE;
}

int aipass_side_of_car_is_okay(NearbyCar *nc, DrivingChoice *choice,
                               int preferred)
{
    // 0x001c7e28.
    Car *car = nc->TheCar;

    if (car->TheControlMode == TRAFFIC_CONTROL)
        return 1;
    if (!(TryToDriveAroundCarMinSpeedForDrivingLine
          < car->State.VelocityMagnitude))
        return 1;
    if (drivingchoice_type_is_driving_line(choice->Type))
        return 1;
    return preferred != 0;
}

int aipass_has_been_accomplished(AIActionPass *a, DrivingInformation *info)
{
    // 0x001c7b90.
    NearbyCarList *list = &info->MyNearbyCarList;
    int done = 0;

    if (list->NumCarsInArray > 0 && list->Array[0].TheCar != a->CarToPass) {
        DrivingChoice c;
        Car *car = NULL;
        float amount = 0.0f;

        drivingchoice_clear(&c);
        if (aipass_calculate_score(info, &car, &c, &amount) >= 0
            && !drivingchoice_is_equal_to(&info->MyDrivingChoice, &c)) {
            info->MyDrivingChoice = c;
            a->CarToPass = car;
            a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
        }
    }
    if (!(seconds_since(&a->MyCreationTime) < AIPA_SETTLE)) {
        NearbyCar *nc = nearbycarlist_get_nearby_car(list, a->CarToPass);

        if (nc == NULL
            || nc->Position.y < -((list->MyHalfSizeD + nc->ApparentHalfSizeD)
                                  + AIPA_BEHIND))
            done = 1;
    }
    if (done)
        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);
    return done;
}

int aipass_has_failed(AIActionPass *a, DrivingInformation *info)
{
    // 0x001c7d48.
    NearbyCarList *list = &info->MyNearbyCarList;
    NearbyCar *nc = nearbycarlist_get_nearby_car(list, a->CarToPass);
    int failed = 0;

    if (nc == NULL)
        failed = 1;
    else if (seconds_since(&a->MyCreationTime) < AIPA_SETTLE
             && 0.0f < nc->Position.y)
        failed = !ai_can_i_catch_this_car(nc, list->MyCar, -1.0f, 0);
    if (failed)
        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);
    return failed;
}

int aipass_has_expired(AIActionPass *a, DrivingInformation *info)
{
    // 0x001c7d00.
    (void)info;
    return past_timeout(&a->Base.Base);
}

void aipass_calculate_points_to_drive(AIActionPass *a,
                                      DrivingInformation *info)
{
    // 0x001c7ea8. Retail leaves f14 stale for TryToDriveAroundCar and
    // IsDriveable, and f13 for BuildDriveTarget; none reads it.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    NearbyCar *nc;
    int preferred = 0;

    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);
    a->Base.UseDrivingLineSpeed = 0;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.AllowedToUseBoost = 1;
    a->Base.PointsToDriveWillExecuteAction = 1;
    nc = nearbycarlist_get_nearby_car(list, a->CarToPass);
    if (nc != NULL) {
        if (0.0f < nc->Position.y) {
            drivingchoice_try_to_drive_around_car(
                choice, &a->Base.PointsToDrive, &preferred, nc, loc, list,
                0.0f, AIDriverAvoidCarsImpactTimeThreshold, 0.0f, 1);
        } else {
            float score = 0.0f, hitTime = AIPA_NO_HIT;
            Car *hitCar = NULL;

            if (!drivingchoice_type_is_driving_line(choice->Type))
                drivingchoice_set_choice_location(choice, loc);
            drivingchoice_is_driveable(choice, &a->Base.PointsToDrive, 0,
                                       &score, &hitCar, &hitTime, loc, list,
                                       0.0f,
                                       AIDriverAvoidCarsImpactTimeThreshold,
                                       0.0f, MOVEMENT_PARALLEL_TO_LINE);
        }
        a->Base.UseDrivingLineSpeed = 1;
    } else {
        if (!drivingchoice_type_is_driving_line(choice->Type))
            drivingchoice_set_choice_location(choice, loc);
        drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive, loc,
                                         list, 0.0f, 0.0f,
                                         MOVEMENT_PARALLEL_TO_LINE);
        a->Base.UseDrivingLineSpeed = 1;
        a->Base.PointsToDriveWillExecuteAction = 0;
    }
}

const char *aipass_get_name(AIActionPass *a)
{
    // 0x001ca978.
    (void)a;
    return "Pass";
}

// --------------------------------------------------------- AvoidCars

typedef int32_t (*CarDriverNumberFn)(void *self);

// The car's driver's GetDriverNumber, through the vptr.
static int32_t driver_number(Car *car)
{
    CarDriver *d = car->pCarDriver;
    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_GET_DRIVER_NUMBER);

    return ((CarDriverNumberFn)e->fn)(vt_this(d, e));
}

AIActionAvoidCars *aiavoidcars_init(AIActionAvoidCars *a, int32_t score,
                                    float timeout, Car *car, float secs,
                                    int okay, int usedPreferred)
{
    // 0x001c6ba0. The two Timers' own constructors zero them first.
    aiaction_init(&a->Base, score, timeout);
    a->LastDecisionReevaluationTime.PackedTime = 0;
    a->MyCreationTime.PackedTime = 0;
    a->Base.Base._vtable = AIAVOIDCARS_VTABLE;
    a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;
    a->CarToAvoid = car;
    a->IsMyDrivingChoiceOkay = okay;
    a->UsedPreferredSide = usedPreferred;
    a->SecondsToImpact = secs;
    a->Base.Type = AIACTION_AVOID_CARS;
    a->MinLifetime = secs + AIAC_MIN_LIFETIME;
    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
    return a;
}

void aiavoidcars_destroy(AIActionAvoidCars *a, int32_t flags)
{
    // 0x001caa00.
    destroy_as(&a->Base, AIAVOIDCARS_VTABLE, flags);
}

int32_t aiavoidcars_calculate_score(DrivingInformation *info, Car **car,
                                    DrivingChoice *choice, float *secs,
                                    int *okay, int *usedPreferred)
{
    // 0x001c6cf8. Retail leaves f13 stale for MakeNewChoice, which does
    // not read it.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    DriveTarget t;
    float hitTime = AIAC_NO_HIT;
    int32_t score = AIA_NO_SCORE;
    Car *hit;

    drivetarget_init(&t);
    drivetarget_clear(&t, NULL, 0.0f);
    *secs = AIAC_NO_HIT;
    *okay = 0;
    *usedPreferred = 0;
    hit = ccp_who_will_this_drive_target_hit(
        &list->MyCar->pCarDriver->MyDriveTarget, list, loc,
        AIDriverAvoidCarsImpactTimeThreshold, &hitTime);
    if (hit != NULL && hitTime < AIDriverAvoidCarsImpactTimeThreshold) {
        int grace;

        *car = hit;
        *secs = hitTime;
        grace = race_grace_period_is_active(pCurrentRace, list->MyCar);
        *choice = info->MyDrivingChoice;
        if (grace && hit->pPlayer == NULL) {
            *okay = 1;
            *usedPreferred = 0;
        } else {
            *okay = drivingchoice_make_new_choice(
                choice, &t, loc, list, AIDriverAvoidCarsImpactTimeThreshold,
                0.0f, usedPreferred, 1);
        }
        score = AIAC_SCORE;
    }
    drivetarget_destroy(&t);
    return score;
}

int aiavoidcars_has_been_accomplished(AIActionAvoidCars *a,
                                      DrivingInformation *info)
{
    // 0x001c6e78. `c.le.s`, so a NaN MinLifetime is past at once.
    int done = !(seconds_since(&a->MyCreationTime) <= a->MinLifetime);

    if (done)
        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);
    return done;
}

int aiavoidcars_has_failed(AIActionAvoidCars *a, DrivingInformation *info)
{
    // 0x001c6ef0.
    (void)a;
    (void)info;
    return 0;
}

int aiavoidcars_has_expired(AIActionAvoidCars *a, DrivingInformation *info)
{
    // 0x001c6ee8.
    (void)a;
    (void)info;
    return 0;
}

void aiavoidcars_calculate_points_to_drive(AIActionAvoidCars *a,
                                           DrivingInformation *info)
{
    // 0x001c6ef8. Retail leaves f13 stale for MakeNewChoice and
    // BuildDriveTarget, and f14 for IsDriveable; none reads it.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    Car *me = list->MyCar;
    NearbyCar *ncChoice = nearbycarlist_get_nearby_car(list, choice->pCar);
    NearbyCar *ncAvoid = nearbycarlist_get_nearby_car(list, a->CarToAvoid);
    int slow = 0, reevaluate;

    drivetarget_assign(&a->Base.PointsToDrive, &me->pCarDriver->MyDriveTarget);
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.UseDrivingLineSpeed = 1;
    // Asked, and the answers dropped.
    ai_do_we_care_about_this_car(ncAvoid, list);
    ai_do_we_care_about_this_car(ncChoice, list);
    if (ncAvoid != NULL && me->State.VelocityMagnitude < AIAC_SLOW_ME
        && ncAvoid->TheCar->State.VelocityMagnitude < AIAC_SLOW_IT)
        slow = 1;
    // The car to avoid is read through, not looked up, so in the grace
    // period it must be a car.
    reevaluate = !race_grace_period_is_active(pCurrentRace, me)
                 || a->CarToAvoid->pPlayer != NULL;
    if (!(AIAC_REEVALUATE_EVERY
          < seconds_since(&a->LastDecisionReevaluationTime)))
        reevaluate = 0;

    if (reevaluate) {
        int used = 0;

        if (drivingchoice_type_is_driving_line(choice->Type) && slow) {
            drivingchoice_set_choice(choice, CHOICE_LEFT_SIDE_OF_CAR,
                                     ncAvoid->TheCar, 0);
            if (!drivingchoice_is_enough_room(choice, ncAvoid, list))
                drivingchoice_set_choice(choice, CHOICE_RIGHT_SIDE_OF_CAR,
                                         ncAvoid->TheCar, 0);
        }
        a->UsedPreferredSide = 0;
        a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice(
            choice, &a->Base.PointsToDrive, loc, list,
            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, &used, 1);
        // Retail hands MakeNewChoice the field itself. Its out is an int,
        // and the field's int32_t is a long on the 3DS.
        a->UsedPreferredSide = used;
        if (drivingchoice_type_is_driving_line(choice->Type)) {
            if (drivingchoice_get_driving_line(choice->Type, me)
                != loc->DrivingLine) {
                drivinglocation_set_driving_line(
                    loc, drivingchoice_get_driving_line(choice->Type, me), 0);
                ai_highlight_driving_line(loc, driver_number(me));
            }
            ncChoice = NULL;
        } else if (drivingchoice_type_is_side_of_car(choice->Type)) {
            ncChoice = nearbycarlist_get_nearby_car(list, choice->pCar);
        }
        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;
    }

    // A choice just made with points stands. Any other is checked again,
    // from the location's line when it is none or no longer valid.
    if (!(a->Base.PointsToDrive.NumPoints != 0 && choice->Type != CHOICE_NONE
          && reevaluate)) {
        float score = -1.0f, hitTime = AIAC_NO_HIT;
        Car *hitCar = NULL;

        if (choice->Type == CHOICE_NONE
            || !drivingchoice_is_valid(choice, loc, list)) {
            a->IsMyDrivingChoiceOkay = 0;
            drivingchoice_set_choice_location(choice, loc);
        }
        a->IsMyDrivingChoiceOkay = drivingchoice_is_driveable(
            choice, &a->Base.PointsToDrive, a->UsedPreferredSide, &score,
            &hitCar, &hitTime, loc, list, 0.0f,
            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, MOVEMENT_TOWARDS_LINE);
        if (a->Base.PointsToDrive.NumPoints == 0) {
            drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive,
                                             loc, list, 0.0f, 0.0f,
                                             MOVEMENT_PARALLEL_TO_LINE);
            a->IsMyDrivingChoiceOkay = 0;
        }
    }

    // No good choice and a car we care about: slow behind the car to
    // avoid, when it is not blinking and is close ahead.
    if (!a->IsMyDrivingChoiceOkay
        && (ai_do_we_care_about_this_car(ncAvoid, list)
            || ai_do_we_care_about_this_car(ncChoice, list))
        && ncAvoid != NULL && !car_is_blinking(ncAvoid->TheCar)) {
        Car *car = ncAvoid->TheCar;
        int close;

        // A real car's place a tenth of a second on, past half my length;
        // any other's, ahead at all.
        if (car->TheControlMode == REAL_CONTROL)
            close = list->MyHalfSizeD * AIAC_HALF
                    < ncAvoid->Position.y
                      + ncAvoid->Velocity.y * AIAC_LOOK_AHEAD;
        else
            close = 0.0f < ncAvoid->Position.y;
        if (!(fabsf(ncAvoid->Position.x)
              < (list->MyHalfSizeL + ncAvoid->ApparentHalfSizeL)
                + AIAC_ACROSS_MARGIN)
            && car->pPlayer == NULL)
            close = 0;
        if (close) {
            a->Base.UseDrivingLineSpeed = 0;
            if (slow)
                a->Base.UseDrivingLineSpeed = 1;
            else
                aiaction_set_desired_speed_slower_than_this_car(
                    &a->Base, ncAvoid, list, AIAC_SLOWER_BY, AIAC_SLOWER_BY);
            if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
                || car->MyDriver->TheDriverType == DRIVER_TYPE_COP)
                a->Base.DesiredSpeed = max_s(a->Base.DesiredSpeed,
                                             AIAC_MIN_SPEED_BEHIND);
        }
    }
    a->Base.PointsToDriveWillExecuteAction = 1;
}

const char *aiavoidcars_get_name(AIActionAvoidCars *a)
{
    // 0x001ca9f0.
    (void)a;
    return "Avoid Cars";
}

Car *aiavoidcars_get_car_to_avoid(AIActionAvoidCars *a)
{
    // 0x001ca9e8.
    return a->CarToAvoid;
}

// --------------------------------------------------------- PullOver

// 0x001c8660, a method that does not read `this`: the room between my car
// and the right edge at `rp`, less my half width.
static float room_to_the_right_edge(NearbyCarList *list,
                                    const TrackRoutePoint *rp)
{
    const Car *me = list->MyCar;

    return (rp->RightWidth - list->MyHalfSizeL)
           - ((me->State.Position.x - rp->Position.x) * rp->Direction.y
              - (me->State.Position.y - rp->Position.y) * rp->Direction.x);
}

// Car+2056 as retail reads it, a word: CopLights and the three bytes after.
static int cop_lights_word(const Car *c)
{
    const uint8_t *p = (const uint8_t *)c + offsetof(Car, CopLights);

    return (p[0] | p[1] | p[2] | p[3]) != 0;
}

// A car with its cop lights on, within 3.5 s at its speed and no less than
// 100 m. The range is worked out before the lights are asked.
static int cop_lights_in_range(const Car *c, const Car *me)
{
    float range = max_s(c->State.VelocityMagnitude * AIPO_LIGHTS_SECONDS,
                        AIPO_LIGHTS_MIN);
    float dx, dy;

    if (!cop_lights_word(c))
        return 0;
    dx = c->State.Position.x - me->State.Position.x;
    dy = c->State.Position.y - me->State.Position.y;
    return sqrtf(dx * dx + dy * dy) <= range;
}

AIActionPullOver *aipullover_init(AIActionPullOver *a, int32_t score,
                                  float timeout, float pullOverTimeout,
                                  NearbyCarList *list, DrivingLocation *loc)
{
    // 0x001c8298. The two Timers' own constructors zero them first.
    aiaction_init(&a->Base, score, timeout);
    a->MyCreationTime.PackedTime = 0;
    a->LastDecisionReevaluationTime.PackedTime = 0;
    a->Base.Base._vtable = AIPULLOVER_VTABLE;
    a->Base.Type = AIACTION_PULL_OVER;
    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
    a->IsMyDrivingChoiceOkay = 1;
    a->PullOverTimeout = pullOverTimeout;
    if (list != NULL && loc != NULL)
        a->New620 = AIPO_ROOM_LOW < room_to_the_right_edge(list,
                                                           loc->pRoutePoint);
    else
        a->New620 = 1;
    a->LastDecisionReevaluationTime.PackedTime = 0;
    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);
    return a;
}

void aipullover_destroy(AIActionPullOver *a, int32_t flags)
{
    // 0x001ca788.
    destroy_as(&a->Base, AIPULLOVER_VTABLE, flags);
}

int32_t aipullover_calculate_score(DrivingInformation *info)
{
    // 0x001c8400. Neither the players nor the cops' cars are tested for
    // NULL; the cops themselves are.
    Car *me = info->MyNearbyCarList.MyCar;
    struct Chopper *h;
    int near = 0, i;

    if (me->TheControlMode != TRAFFIC_CONTROL)
        return AIA_NO_SCORE;
    h = pCurrentWorld->Helicopter;
    // The plan by `sltiu`, so a negative one is none of 0 to 2.
    if (h != NULL
        && ((uint32_t)h->Plan < 3u || h->Plan == CHOPPLAN_BOMBING_RUN)) {
        float dx = h->CurrentPos.x - me->State.Position.x;
        float dy = h->CurrentPos.y - me->State.Position.y;

        if (sqrtf(dx * dx + dy * dy) <= AIPO_CHOPPER_RANGE)
            near = 1;
    }
    if (pCopManager != NULL) {
        const tCopManagerHead *m = copmanager_head(pCopManager);

        for (i = 0; i < m->nNumAICops && !near; i++) {
            const tCop *cop = m->Cops[i];

            if (cop == NULL || cop->DesiredLogicState == LS_DISABLED)
                continue;
            if (cop_lights_in_range(cop->pMyCar, me))
                near = 1;
        }
    }
    for (i = 0; i < PlayerNumPlayers && !near; i++)
        if (cop_lights_in_range(PlayerPlayersByIndex[i]->MyCar, me))
            near = 1;
    return near ? AIPO_SCORE : AIA_NO_SCORE;
}

int aipullover_has_been_accomplished(AIActionPullOver *a,
                                     DrivingInformation *info)
{
    // 0x001c8610.
    (void)a;
    if (info->MyNearbyCarList.MyCar->TheControlMode != TRAFFIC_CONTROL)
        return 0;
    return aipullover_calculate_score(info) == AIA_NO_SCORE;
}

int aipullover_has_failed(AIActionPullOver *a, DrivingInformation *info)
{
    // 0x001c8658.
    (void)a;
    (void)info;
    return 0;
}

int aipullover_has_expired(AIActionPullOver *a, DrivingInformation *info)
{
    // 0x001c8650.
    (void)a;
    (void)info;
    return 0;
}

void aipullover_calculate_points_to_drive(AIActionPullOver *a,
                                          DrivingInformation *info)
{
    // 0x001c86a8. Retail leaves f13 stale for BuildDriveTarget and
    // MakeNewChoice, neither of which reads it.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    Car *me = list->MyCar;
    int careful;

    drivetarget_assign(&a->Base.PointsToDrive, &me->pCarDriver->MyDriveTarget);
    a->Base.UseDrivingLineSpeed = 0;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.AllowedToUseBoost = 0;
    careful = me->MyDriver->SkillLevel == AIPO_CAREFUL_SKILL;

    if (fabsf(a->PullOverTimeout - AIPO_NO_TIMEOUT) <= AIPO_TIMEOUT_EPSILON
        || seconds_since(&a->MyCreationTime) < a->PullOverTimeout) {
        float speed;

        if (AIPO_REEVALUATE_EVERY
                < seconds_since(&a->LastDecisionReevaluationTime)
            || a->Base.PointsToDrive.NumPoints == 0) {
            float hitTime = 0.0f;
            Car *hit;

            a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;
            if (!drivingchoice_type_is_driving_line(choice->Type))
                drivingchoice_set_choice_location(choice, loc);
            a->IsMyDrivingChoiceOkay = 1;
            if (careful) {
                drivingchoice_build_drive_target(choice,
                                                 &a->Base.PointsToDrive, loc,
                                                 list, 0.0f, 0.0f,
                                                 MOVEMENT_PARALLEL_TO_LINE);
            } else {
                drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);
                drivingchoice_fill_up_drive_target(
                    &a->Base.PointsToDrive, loc, list,
                    MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK, 0);
            }
            hit = ccp_who_will_this_drive_target_hit(
                &a->Base.PointsToDrive, list, loc,
                AIDriverAvoidCarsImpactTimeThreshold, &hitTime);
            if (hit != NULL && hitTime < AIPO_HIT_SOON) {
                DriveTarget t;
                DrivingChoice c;
                int usedPreferred = 1;

                drivetarget_init(&t);
                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, hit, 0);
                a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice(
                    &c, &t, loc, list, AIDriverAvoidCarsImpactTimeThreshold,
                    0.0f, &usedPreferred, 1);
                drivetarget_assign(&a->Base.PointsToDrive, &t);
                *choice = c;
                drivetarget_destroy(&t);
            }
        }

        speed = me->State.VelocityMagnitude;
        if (careful) {
            if (a->IsMyDrivingChoiceOkay)
                a->Base.DesiredSpeed =
                    speed + ai_calculate_max_deceleration(me, speed)
                            * AIPO_GENTLE;
            else
                a->Base.DesiredSpeed =
                    speed + ai_calculate_max_deceleration(me, speed)
                            * AIPO_FIRM;
        } else if (drivinglocation_is_clear(loc)
                   || !a->IsMyDrivingChoiceOkay) {
            aiaction_set_desired_speed_to_max_deceleration(&a->Base, me,
                                                           AIPO_BRAKE);
        } else {
            int stop;

            // New620 holds while the room to the edge is over 2 m, and
            // comes back over 4.
            if (AIPO_TOO_FAST < speed) {
                a->New620 = 1;
                stop = 1;
            } else {
                float room = room_to_the_right_edge(list, loc->pRoutePoint);

                if (a->New620) {
                    if (room < AIPO_ROOM_LOW)
                        a->New620 = 0;
                } else if (AIPO_ROOM_HIGH < room) {
                    a->New620 = 1;
                }
                stop = !a->New620;
            }
            if (stop)
                aiaction_set_desired_speed_to_max_deceleration(&a->Base, me,
                                                               AIPO_BRAKE);
            else
                a->Base.DesiredSpeed = AIPO_CREEP_SPEED;
            a->Base.DesiredSpeedTolerance = AIPO_TOLERANCE;
        }

        // Stopped, or touching another car: stop.
        if (a->Base.DesiredSpeed < AIPO_STOPPED) {
            a->Base.DesiredSpeed = 0.0f;
            a->Base.DesiredSpeedTolerance = 0.0f;
        } else {
            CollisionBody *b = &me->pDynamicCollisionBody->Dynamic.Body;
            int32_t i;

            for (i = 0; i < b->NumCollisions; i++)
                if (collision_is_two_car_collision(
                        collisionbody_get_collision(b, i))) {
                    a->Base.DesiredSpeed = 0.0f;
                    a->Base.DesiredSpeedTolerance = 0.0f;
                    break;
                }
        }
    } else {
        // Past the timeout: the location's line, at a stop. Retail's
        // choice is its stack until SetChoice, which leaves it alone for
        // a negative odd line; the port's is cleared.
        DrivingChoice c;

        drivingchoice_clear(&c);
        drivingchoice_set_choice_location(&c, loc);
        drivingchoice_build_drive_target(&c, &a->Base.PointsToDrive, loc,
                                         list, 0.0f, 0.0f,
                                         MOVEMENT_PARALLEL_TO_LINE);
        a->Base.DesiredSpeedTolerance = 0.0f;
        a->Base.DesiredSpeed = 0.0f;
    }
    a->Base.PointsToDriveWillExecuteAction = 1;
    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;
}

const char *aipullover_get_name(AIActionPullOver *a)
{
    // 0x001ca778.
    (void)a;
    return "Pull over";
}

// ------------------------------------------------------- IJustGotHit

AIActionIJustGotHit *aijustgothit_init(AIActionIJustGotHit *a, int32_t score,
                                       float timeout, Car *car)
{
    // 0x001c9c68.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_I_JUST_GOT_HIT;
    a->CarIHit = car;
    a->Base.Base._vtable = AIIJUSTGOTHIT_VTABLE;
    a->LastDecisionReevaluationTime.PackedTime = 0;
    return a;
}

void aijustgothit_destroy(AIActionIJustGotHit *a, int32_t flags)
{
    // 0x001ca638.
    destroy_as(&a->Base, AIIJUSTGOTHIT_VTABLE, flags);
}

int32_t aijustgothit_calculate_score(DrivingInformation *info, Car **car)
{
    // 0x001c9d20. Of the two-car collisions whose other car is on the
    // list, the last one that beats the one held: any does when none is
    // held (or the held car is NULL), one ahead does when the held one is
    // behind, and otherwise a smaller y does.
    NearbyCarList *list = &info->MyNearbyCarList;
    CollisionBody *b = &list->MyCar->pDynamicCollisionBody->Dynamic.Body;
    NearbyCar *best = NULL;
    Car *bestCar = NULL;
    int found = 0;
    int32_t i;

    *car = NULL;
    for (i = 0; i < b->NumCollisions; i++) {
        Collision *c = collisionbody_get_collision(b, i);
        Car *c1 = NULL, *c2 = NULL, *other;
        NearbyCar *nc;
        int take;

        if (!collision_is_two_car_collision(c))
            continue;
        collision_get_colliding_cars(c, &c1, &c2);
        other = c1 == list->MyCar ? c2 : c1;
        nc = nearbycarlist_get_nearby_car(list, other);
        if (nc == NULL)
            continue;
        if (best == NULL || bestCar == NULL)
            take = 1;
        else if (best->Position.y < 0.0f && 0.0f < nc->Position.y)
            take = 1;
        else
            take = nc->Position.y < best->Position.y;
        if (take) {
            bestCar = other;
            best = nc;
            found = 1;
        }
    }
    if (!found)
        return AIA_NO_SCORE;
    *car = bestCar;
    return AIIJ_SCORE;
}

int aijustgothit_has_been_accomplished(AIActionIJustGotHit *a,
                                       DrivingInformation *info)
{
    // 0x001c9e90.
    Car *car = NULL;
    int none = aijustgothit_calculate_score(info, &car) == AIA_NO_SCORE;

    if (!none)
        a->CarIHit = car;
    if (a->CarIHit == NULL
        || nearbycarlist_get_nearby_car(&info->MyNearbyCarList, a->CarIHit)
           == NULL)
        return 1;
    return none;
}

int aijustgothit_has_failed(AIActionIJustGotHit *a, DrivingInformation *info)
{
    // 0x001c9f58.
    (void)a;
    (void)info;
    return 0;
}

int aijustgothit_has_expired(AIActionIJustGotHit *a, DrivingInformation *info)
{
    // 0x001c9f10.
    (void)info;
    return past_timeout(&a->Base.Base);
}

void aijustgothit_calculate_points_to_drive(AIActionIJustGotHit *a,
                                            DrivingInformation *info)
{
    // 0x001c9f60. Retail leaves f13 stale for MakeNewChoice, which does
    // not read it.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    NearbyCar *nc = nearbycarlist_get_nearby_car(list, a->CarIHit);
    Car *me;

    drivetarget_assign(&a->Base.PointsToDrive,
                       &list->MyCar->pCarDriver->MyDriveTarget);
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.UseDrivingLineSpeed = 0;
    if (AIIJ_REEVALUATE_EVERY < seconds_since(&a->LastDecisionReevaluationTime)
        || a->Base.PointsToDrive.NumPoints == 0) {
        int usedPreferred = 0;

        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;
        drivingchoice_make_new_choice(&info->MyDrivingChoice,
                                      &a->Base.PointsToDrive, loc, list,
                                      AIDriverAvoidCarsImpactTimeThreshold,
                                      0.0f, &usedPreferred, 1);
    }
    me = list->MyCar;

    if (aiaction_get_heading_classification(loc, me, 0)
        == HEADING_OUT_OF_ROUTE_FORWARDS) {
        aiaction_set_desired_speed_to_max_deceleration(&a->Base, me,
                                                       AIIJ_BRAKE);
    } else if (nc == NULL) {
        a->Base.UseDrivingLineSpeed = 1;
    } else if (a->CarIHit->pPlayer != NULL
               && me->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR) {
        // A player's car, and I am no traffic: back off from it when it
        // is clear ahead, get away when it is clear behind.
        if ((list->MyHalfSizeD + nc->ApparentHalfSizeD) - AIIJ_OVERLAP
            < nc->Position.y)
            aiaction_set_desired_speed_slower_than_this_car(
                &a->Base, nc, list, AIIJ_BACK_OFF, AIIJ_SLOWER_UNUSED);
        else if (nc->Position.y
                 < (-list->MyHalfSizeD - nc->ApparentHalfSizeD)
                   + AIIJ_OVERLAP)
            aiaction_set_desired_speed_to_max_acceleration(&a->Base, me,
                                                           AIIJ_ACCEL);
        else
            a->Base.UseDrivingLineSpeed = 1;
    } else if (!(0.0f < nc->Position.y)) {
        aiaction_set_desired_speed_to_max_acceleration(&a->Base, me,
                                                       AIIJ_ACCEL);
    } else if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
               && me->State.BodyMatrix.v0.x
                      * a->CarIHit->State.BodyMatrix.v0.x
                  + me->State.BodyMatrix.v0.y
                      * a->CarIHit->State.BodyMatrix.v0.y
                  < 0.0f) {
        // Traffic hit head on by a car ahead: hold the speed, hands off.
        a->Base.TimeToGetToDesiredSpeed = 0.0f;
        a->Base.DesiredSpeed = me->State.VelocityMagnitude;
        a->Base.AllowedToUseThrottleAndBrake = 0;
    } else {
        aiaction_set_desired_speed_slower_than_this_car(
            &a->Base, nc, list, AIIJ_SLOWER_BY, AIIJ_SLOWER_UNUSED);
    }

    if (!a->Base.UseDrivingLineSpeed && a->Base.DesiredSpeed < AIIJ_MIN_SPEED)
        a->Base.DesiredSpeed = AIIJ_MIN_SPEED;
    a->Base.PointsToDriveWillExecuteAction = 1;
}

const char *aijustgothit_get_name(AIActionIJustGotHit *a)
{
    // 0x001ca628.
    (void)a;
    return "I just got hit!";
}

// -------------------------------------------------------- GetUnstuck

typedef void (*AIActionsVoidFn)(void *self);

// The car's controller's FindWhereIAm, through the vptr.
static void find_where_i_am(Car *car)
{
    CarController *c = car->pCarController;
    const VtEntry *e = vt_slot(c->_vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);

    ((AIActionsVoidFn)e->fn)(vt_this(c, e));
}

// The car's driver's ClearSteeringMemory, through the vptr.
static void clear_steering_memory(Car *car)
{
    CarDriver *d = car->pCarDriver;
    const VtEntry *e = vt_slot(d->_vtable,
                               CARDRIVER_VT_CLEAR_STEERING_MEMORY);

    ((AIActionsVoidFn)e->fn)(vt_this(d, e));
}

// How far `p` is to the right of the route point's line, across its
// direction.
static float across(const bVector2 *p, const TrackRoutePoint *rp)
{
    return (p->x - rp->Position.x) * rp->Direction.y
           - (p->y - rp->Position.y) * rp->Direction.x;
}

// How far `l` across the point is past the road's edge on its side:
// negative on the road.
static float past_the_edge(float l, const TrackRoutePoint *rp)
{
    if (0.0f < l)
        return l - rp->RightWidth;
    return -(l + rp->LeftWidth);
}

// The minimum lifetime is in effect and not yet up: `c.le.s` the lifetime
// against the seconds, so a NaN is not up.
static int too_young(const AIActionGetUnstuck *a)
{
    return a->MinimumLifetimeInEffect != 0
           && !(a->MinimumLifetime <= seconds_since(&a->MyCreationTime));
}

// 0x001c9018, a method that does not read `this`: three points on from the
// location's, in the same table. Retail tests that for NULL, which it
// never is, and takes the route's last point then; past the route's end
// it reads on into the table.
static const TrackRoutePoint *goal_route_point(const DrivingLocation *loc)
{
    const TrackRoute *r = loc->pRoute;

    return &r->TrackRoutePointTable[(loc->pRoutePoint
                                     - r->TrackRoutePointTable)
                                    + AIGU_GOAL_AHEAD];
}

// 0x001c9070 and 0x001c90d8, the same: the goal point on the location's
// line.
static void goal_point2(const DrivingLocation *loc, bVector2 *out)
{
    const TrackRoutePoint *p = goal_route_point(loc);

    trpoint_get_position2(p, out, 0.0f,
                          trpoint_get_driving_line_offset(
                              p, loc->DrivingLine));
}

static void goal_point3(const DrivingLocation *loc, bVector3 *out)
{
    const TrackRoutePoint *p = goal_route_point(loc);

    trpoint_get_position3(p, out, 0.0f,
                          trpoint_get_driving_line_offset(
                              p, loc->DrivingLine));
}

AIActionGetUnstuck *aigetunstuck_init(AIActionGetUnstuck *a, int32_t score,
                                      float timeout, float minLifetime)
{
    // 0x001c8b30. The Timer's own constructor zeroes it first.
    aiaction_init(&a->Base, score, timeout);
    a->MyCreationTime.PackedTime = 0;
    a->Base.Base._vtable = AIGETUNSTUCK_VTABLE;
    a->Base.Type = AIACTION_GET_UNSTUCK;
    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;
    a->MinimumLifetime = minLifetime;
    a->MinimumLifetimeInEffect =
        !(fabsf(minLifetime - AIGU_NO_LIFETIME) <= AIGU_LIFETIME_EPSILON);
    return a;
}

void aigetunstuck_destroy(AIActionGetUnstuck *a, int32_t flags)
{
    // 0x001ca6a8.
    destroy_as(&a->Base, AIGETUNSTUCK_VTABLE, flags);
}

int32_t aigetunstuck_calculate_score(DrivingInformation *info)
{
    // 0x001c8c30.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    Car *me = list->MyCar;
    CollisionBody *b;
    int stuck = 0;
    int32_t i;

    if (race_grace_period_is_active(pCurrentRace, me)
        || drivinglocation_is_clear(loc)
        || me->State.nWheelsTouchingGround < 3)
        return AIA_NO_SCORE;
    if (loc->pRoutePoint != NULL) {
        bVector2 pos;

        pos.x = me->State.Position.x;
        pos.y = me->State.Position.y;
        if (AIGU_OFF_ROAD <= past_the_edge(across(&pos, loc->pRoutePoint),
                                           loc->pRoutePoint))
            stuck = 1;
    }
    if (!stuck
        && ((me->TheControlMode == AI_CONTROL
             && me->State.VelocityMagnitude <= AIGU_SLOW_AI)
            || (me->TheControlMode == TRAFFIC_CONTROL
                && me->State.VelocityMagnitude <= AIGU_SLOW_TRAFFIC))
        && aiaction_get_heading_classification(loc, me, 1)
           == HEADING_OUT_OF_ROUTE_FORWARDS)
        stuck = 1;
    if (!stuck)
        stuck = aigetunstuck_are_we_stuck_behind_someone(loc, list);

    // Nosed into something and all but stopped.
    b = &me->pDynamicCollisionBody->Dynamic.Body;
    for (i = 0; i < b->NumCollisions && !stuck; i++) {
        Collision *c = collisionbody_get_collision(b, i);
        float v;

        if (aiaction_get_collision_classification(c, me)
            != COLLISION_IN_FRONT)
            continue;
        if (!(AIGU_HIT_AGO <= seconds_since(&c->CollisionTime)))
            continue;
        v = me->State.VelocityMagnitude;
        if (v < AIGU_STOPPED
            || fabsf(v - AIGU_STOPPED) <= AIGU_STOPPED_EPSILON)
            stuck = 1;
    }
    if (!stuck)
        return AIA_NO_SCORE;
    find_where_i_am(me);
    return AIGU_SCORE;
}

int aigetunstuck_are_we_stuck_behind_someone(DrivingLocation *loc,
                                             NearbyCarList *list)
{
    // 0x001c8ee8, static. Retail takes the absolute value of -15 to test
    // my speed against, and does not take mine's. An entry with no car is
    // read through.
    Car *me = list->MyCar;
    int stuck = 0;
    int32_t i;

    (void)loc;
    if (car_is_blinking(me))
        return 0;
    if (!(me->State.VelocityMagnitude <= fabsf(AIGU_REVERSE_AI)))
        return 0;
    for (i = 0; i < list->NumCarsInArray && !stuck; i++) {
        const NearbyCar *nc = &list->Array[i];

        if (nc->TheCar == me)
            continue;
        if (!(fabsf(nc->TheCar->State.VelocityMagnitude) <= AISlowCarSpeed))
            continue;
        if (!(fabsf(nc->Position.x)
              < list->MyHalfSizeL + nc->ApparentHalfSizeL))
            continue;
        if (!(0.0f < nc->Position.y))
            continue;
        if (nc->Position.y
            < (list->MyHalfSizeD + nc->ApparentHalfSizeD) + AIGU_BEHIND_GAP)
            stuck = 1;
    }
    return stuck;
}

int aigetunstuck_has_been_accomplished(AIActionGetUnstuck *a,
                                       DrivingInformation *info)
{
    // 0x001c9140. Both directions are normalised in place.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    bVector2 goal, to, fwd;
    int done = 0;

    if (too_young(a))
        return 0;
    goal_point2(loc, &goal);
    to.x = goal.x - list->MyCar->State.Position.x;
    to.y = goal.y - list->MyCar->State.Position.y;
    bNormalize2(&to, &to);
    fwd.x = list->MyCar->State.BodyMatrix.v0.x;
    fwd.y = list->MyCar->State.BodyMatrix.v0.y;
    bNormalize2(&fwd, &fwd);
    if (AIGU_FACING <= fwd.x * to.x + fwd.y * to.y)
        done = !aigetunstuck_are_we_stuck_behind_someone(loc, list);
    if (done) {
        find_where_i_am(list->MyCar);
        clear_steering_memory(list->MyCar);
    }
    return done;
}

int aigetunstuck_has_failed(AIActionGetUnstuck *a, DrivingInformation *info)
{
    // 0x001c9340.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    Car *me = list->MyCar;
    int failed = 0;

    if (drivinglocation_is_clear(loc) || me->State.nWheelsTouchingGround < 3) {
        failed = 1;
    } else if (too_young(a)) {
        return 0;
    } else if (aiaction_get_heading_classification(loc, me, 1)
               == HEADING_OUT_OF_ROUTE_BACKWARDS) {
        failed = 1;
    } else {
        // Backed into something and all but stopped.
        CollisionBody *b = &me->pDynamicCollisionBody->Dynamic.Body;
        int32_t i;

        for (i = 0; i < b->NumCollisions && !failed; i++) {
            Collision *c = collisionbody_get_collision(b, i);
            float v;

            if (aiaction_get_collision_classification(c, me)
                != COLLISION_BEHIND)
                continue;
            if (!(AIGU_HIT_AGO <= seconds_since(&c->CollisionTime)))
                continue;
            v = me->State.VelocityMagnitude;
            if (fabsf(v) < AIGU_STOPPED
                || fabsf(v - AIGU_STOPPED) <= AIGU_STOPPED_EPSILON)
                failed = 1;
        }
    }
    if (failed) {
        find_where_i_am(me);
        clear_steering_memory(me);
    }
    return failed;
}

int aigetunstuck_has_expired(AIActionGetUnstuck *a, DrivingInformation *info)
{
    // 0x001c9298.
    int expired = past_timeout(&a->Base.Base);

    if (expired) {
        find_where_i_am(info->MyNearbyCarList.MyCar);
        clear_steering_memory(info->MyNearbyCarList.MyCar);
    }
    return expired;
}

void aigetunstuck_calculate_points_to_drive(AIActionGetUnstuck *a,
                                            DrivingInformation *info)
{
    // 0x001c9550.
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    bVector3 goal;

    if (!drivingchoice_type_is_driving_line(choice->Type))
        drivingchoice_set_choice_location(choice, loc);
    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.UseDrivingLineSpeed = 0;
    a->Base.AllowedToUseBoost = 0;
    a->Base.PointsToDriveWillExecuteAction = 1;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    if (drivinglocation_is_clear(loc)) {
        a->Base.PointsToDriveWillExecuteAction = 0;
        return;
    }
    goal_point3(loc, &goal);
    goal.pad = 0.0f;   // STACK-W
    drivetarget_add_point3_dl(&a->Base.PointsToDrive, &goal, loc, 0, NULL);
    drivingchoice_fill_up_drive_target(&a->Base.PointsToDrive, loc,
                                       &info->MyNearbyCarList,
                                       MOVEMENT_PARALLEL_TO_LINE, 1);
    if (info->MyNearbyCarList.MyCar->TheControlMode == AI_CONTROL)
        a->Base.DesiredSpeed = AIGU_REVERSE_AI;
    else
        a->Base.DesiredSpeed = AIGU_REVERSE;
}

const char *aigetunstuck_get_name(AIActionGetUnstuck *a)
{
    // 0x001ca698.
    (void)a;
    return "Get Unstuck";
}

// ---------------------------------------------------- AvoidRoadBlock

AIActionAvoidRoadBlock *aiavoidroadblock_init(AIActionAvoidRoadBlock *a,
                                              int32_t score, float timeout,
                                              const tRoadBlock *rb)
{
    // 0x001c9668.
    aiaction_init(&a->Base, score, timeout);
    a->Base.Type = AIACTION_AVOID_ROADBLOCK;
    a->RoadBlockToAvoid = rb;
    a->Base.Base._vtable = AIAVOIDROADBLOCK_VTABLE;
    return a;
}

void aiavoidroadblock_destroy(AIActionAvoidRoadBlock *a, int32_t flags)
{
    // 0x001ca718.
    destroy_as(&a->Base, AIAVOIDROADBLOCK_VTABLE, flags);
}

int32_t aiavoidroadblock_calculate_score(DrivingInformation *info,
                                         const tRoadBlock **rb)
{
    // 0x001c9718. The roadblock found is asked for again, and its spike
    // belt put in my car's frame; nothing reads that.
    Car *me = info->MyNearbyCarList.MyCar;
    float range;
    int found = 0;
    int32_t i;

    *rb = NULL;
    if (pCopManager == NULL)
        return AIA_NO_SCORE;
    range = max_s(me->State.VelocityMagnitude * AIRB_LOOK_SECONDS,
                  AIRB_LOOK_MIN);
    for (i = 0;
         i < copmanager_get_num_active_road_blocks(pCopManager) && !found;
         i++) {
        tRoadBlock *r = copmanager_get_active_road_block(pCopManager, i);

        if (r->cops[0] == NULL && r->cops[1] == NULL)
            continue;
        if (trackpath_compare_distances(
                &TheTrackPathManager,
                me->TheTrackPathCoordinate.DistanceAroundTrack,
                r->fDistanceAroundTrack) < -range) {
            bVector2 local;

            *rb = r;
            found = 1;
            car_world_to_car(
                info->MyNearbyCarList.MyCar, &local,
                &copmanager_get_active_road_block(pCopManager, i)
                     ->v2SpikeBeltPos);
        }
    }
    return found ? AIRB_SCORE : AIA_NO_SCORE;
}

int aiavoidroadblock_has_been_accomplished(AIActionAvoidRoadBlock *a,
                                           DrivingInformation *info)
{
    // 0x001c9858.
    const tRoadBlock *rb = a->RoadBlockToAvoid;

    if (rb->cops[0] == NULL && rb->cops[1] == NULL)
        return 1;
    return AIRB_PASSED
           < trackpath_compare_distances(
               &TheTrackPathManager,
               info->MyNearbyCarList.MyCar->TheTrackPathCoordinate
                   .DistanceAroundTrack,
               rb->fDistanceAroundTrack);
}

int aiavoidroadblock_has_failed(AIActionAvoidRoadBlock *a,
                                DrivingInformation *info)
{
    // 0x001c98d8.
    (void)a;
    (void)info;
    return 0;
}

int aiavoidroadblock_has_expired(AIActionAvoidRoadBlock *a,
                                 DrivingInformation *info)
{
    // 0x001c98d0.
    (void)a;
    (void)info;
    return 0;
}

void aiavoidroadblock_calculate_points_to_drive(AIActionAvoidRoadBlock *a,
                                                DrivingInformation *info)
{
    // 0x001c98e0. The FuturePointList is on retail's stack, its count
    // zeroed by its constructor.
    NearbyCarList *list = &info->MyNearbyCarList;
    DrivingLocation *loc = &info->MyDrivingLocation;
    DrivingChoice *choice = &info->MyDrivingChoice;
    const tRoadBlock *rb;
    TrackRoutePoint *end;
    FuturePointList l;
    bVector2 pos, escape;
    float fromL, toL, hitTime;
    Car *hit;

    if (!drivingchoice_type_is_driving_line(choice->Type))
        drivingchoice_set_choice_location(choice, loc);
    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);
    a->Base.DesiredSpeedTolerance = 0.0f;
    a->Base.AllowedToUseThrottleAndBrake = 1;
    a->Base.UseDrivingLineSpeed = 0;

    // From my offset off the line to the escape lane's.
    pos.x = list->MyCar->State.Position.x;
    pos.y = list->MyCar->State.Position.y;
    fromL = across(&pos, loc->pRoutePoint)
            - trpoint_get_driving_line_offset(loc->pRoutePoint,
                                              loc->DrivingLine);
    rb = a->RoadBlockToAvoid;
    escape = rb->v2EscapeLane;
    if (loc->pRoute == rb->Route) {
        end = rb->RoutePoint;
        toL = across(&escape, end)
              - trpoint_get_driving_line_offset(end, loc->DrivingLine);
    } else {
        end = troute_find_closest_point_ahead(loc->pRoute, &escape,
                                              loc->pRoutePoint);
        if (end != NULL
            && past_the_edge(across(&escape, end), end) < AIRB_ON_ROAD) {
            toL = across(&escape, end)
                  - trpoint_get_driving_line_offset(end, loc->DrivingLine);
        } else {
            // No escape on this route: to its last point, keeping my
            // offset.
            end = &loc->pRoute->TrackRoutePointTable[loc->pRoute->NumPoints
                                                      - 1];
            toL = fromL;
        }
    }

    l.NumPoints = 0;
    drivingchoice_get_route_points_up_to(&l, loc, end);
    drivingchoice_do_smooth_offset_change(&l, &a->Base.PointsToDrive, list,
                                          l.NumPoints - 1, fromL, toL, 0);
    drivingchoice_fill_up_drive_target(&a->Base.PointsToDrive, loc, list,
                                       MOVEMENT_PARALLEL_TO_LINE, 0);
    a->Base.UseDrivingLineSpeed = 1;

    // A racer in the way, ahead: slow behind it.
    hitTime = 0.0f;
    hit = ccp_who_will_this_drive_target_hit(&a->Base.PointsToDrive, list,
                                             loc, AIRB_HIT_WITHIN, &hitTime);
    if (hit != NULL && hit->pCarTypeInfo->UsageType != CAR_USAGE_TYPE_COP
        && hit->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR) {
        NearbyCar *nc = nearbycarlist_get_nearby_car(list, hit);

        if (nc != NULL && 0.0f < nc->Position.y) {
            a->Base.UseDrivingLineSpeed = 0;
            aiaction_set_desired_speed_slower_than_this_car(
                &a->Base, nc, list, AIRB_SLOWER_BY, AIRB_SLOWER_BY);
            a->Base.DesiredSpeed = max_s(a->Base.DesiredSpeed,
                                         AIRB_MIN_SPEED);
        }
    }
    a->Base.PointsToDriveWillExecuteAction = 1;
}

const char *aiavoidroadblock_get_name(AIActionAvoidRoadBlock *a)
{
    // 0x001ca708.
    (void)a;
    return "Avoid Roadblock";
}

// ------------------------------------------------------------- the replay

// The car pointers go by number, through the world.
#define CAR_PTR(pp) world_do_car_pointer_snapshot(pCurrentWorld, (pp), s)
#define TIMER(t) ReplaySnapshot_MoveTimer(s, (int32_t *)&(t).PackedTime)

void aiavoidcars_do_snapshot(AIActionAvoidCars *a, ReplaySnapshot *s)
{
    // 0x001c6c48.
    ReplaySnapshot_BeginNamedSection(s, "AIActionAvoidCars");
    CAR_PTR(&a->CarToAvoid);
    ReplaySnapshot_MoveFloat(s, &a->SecondsToImpact);
    ReplaySnapshot_MoveBool(s, &a->IsMyDrivingChoiceOkay, 1);
    ReplaySnapshot_MoveBool(s, &a->UsedPreferredSide, 1);
    TIMER(a->LastDecisionReevaluationTime);
    TIMER(a->MyCreationTime);
    ReplaySnapshot_MoveFloat(s, &a->MinLifetime);
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void aijustdrive_do_snapshot(AIActionJustDrive *a, ReplaySnapshot *s)
{
    // 0x001c7400.
    ReplaySnapshot_BeginNamedSection(s, "AIActionJustDrive");
    aiaction_do_snapshot(&a->Base, s);
    TIMER(a->LastDecisionReevaluationTime);
    ReplaySnapshot_EndNamedSection(s);
}

void aidraft_do_snapshot(AIActionDraft *a, ReplaySnapshot *s)
{
    // 0x001c76d0.
    ReplaySnapshot_BeginNamedSection(s, "AIActionDraft");
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void aipass_do_snapshot(AIActionPass *a, ReplaySnapshot *s)
{
    // 0x001c7960. Its own fields last to first.
    ReplaySnapshot_BeginNamedSection(s, "AIActionPass");
    TIMER(a->MyCreationTime);
    ReplaySnapshot_MoveFloat(s, &a->AmountToProjectIntoFuture);
    CAR_PTR(&a->CarToPass);
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void ainudgecar_do_snapshot(AIActionNudgeCar *a, ReplaySnapshot *s)
{
    // 0x001c8078.
    ReplaySnapshot_BeginNamedSection(s, "AIActionNudgeCar");
    CAR_PTR(&a->CarToNudge);
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void aiblock_do_snapshot(AIActionBlock *a, ReplaySnapshot *s)
{
    // 0x001c81b0.
    ReplaySnapshot_BeginNamedSection(s, "AIActionBlock");
    CAR_PTR(&a->CarToBlock);
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void aipullover_do_snapshot(AIActionPullOver *a, ReplaySnapshot *s)
{
    // 0x001c8370.
    ReplaySnapshot_BeginNamedSection(s, "AIActionPullOver");
    aiaction_do_snapshot(&a->Base, s);
    TIMER(a->MyCreationTime);
    TIMER(a->LastDecisionReevaluationTime);
    ReplaySnapshot_MoveBool(s, &a->IsMyDrivingChoiceOkay, 1);
    ReplaySnapshot_MoveBool(s, &a->New620, 1);
    ReplaySnapshot_MoveFloat(s, &a->PullOverTimeout);
    ReplaySnapshot_EndNamedSection(s);
}

void aigetunstuck_do_snapshot(AIActionGetUnstuck *a, ReplaySnapshot *s)
{
    // 0x001c8bb8.
    ReplaySnapshot_BeginNamedSection(s, "AIActionGetUnstuck");
    TIMER(a->MyCreationTime);
    ReplaySnapshot_MoveFloat(s, &a->MinimumLifetime);
    ReplaySnapshot_MoveBool(s, &a->MinimumLifetimeInEffect, 1);
    aiaction_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

void aiavoidroadblock_do_snapshot(AIActionAvoidRoadBlock *a,
                                  ReplaySnapshot *s)
{
    // 0x001c96b8. The roadblock by its index in the cop manager's.
    ReplaySnapshot_BeginNamedSection(s, "AIActionAvoidRoadBlock");
    aiaction_do_snapshot(&a->Base, s);
    copmanager_do_road_block_pointer_snapshot(
        pCopManager, s, (tRoadBlock **)&a->RoadBlockToAvoid);
    ReplaySnapshot_EndNamedSection(s);
}

void aijustgothit_do_snapshot(AIActionIJustGotHit *a, ReplaySnapshot *s)
{
    // 0x001c9cb8.
    ReplaySnapshot_BeginNamedSection(s, "AIActionIJustGotHit");
    aiaction_do_snapshot(&a->Base, s);
    CAR_PTR(&a->CarIHit);
    TIMER(a->LastDecisionReevaluationTime);
    ReplaySnapshot_EndNamedSection(s);
}

void aiaccidentrecovery_do_snapshot(AIActionAccidentRecovery *a,
                                    ReplaySnapshot *s)
{
    // 0x001ca240. Retail names its section IJustGotHit's: the string at
    // 0x002b7938 is passed by both.
    ReplaySnapshot_BeginNamedSection(s, "AIActionIJustGotHit");
    aiaction_do_snapshot(&a->Base, s);
    TIMER(a->MyCreationTime);
    ReplaySnapshot_MoveBool(s, &a->HaveResetYet, 1);
    ReplaySnapshot_EndNamedSection(s);
}

#undef TIMER
#undef CAR_PTR

void aiaction_do_pointer_snapshot(AIAction **pp, ReplaySnapshot *s)
{
    // 0x001c6268, a static of AIAction's. Whether there is one, as a
    // byte; with none, nothing else, and a restore leaves *pp alone.
    // Then the type's low byte. A restore news a fresh action of that
    // type from the pool -- the old one is not freed -- or, for a type of
    // 11 or more, keeps the one there is. Then the action's own DoSnapshot.
    AIAction *a = *pp;
    int8_t    have = (int8_t)(a != NULL);
    int32_t   type = 0;     // retail's stack word, only set from an action
    typedef void (*SnapFn)(void *, ReplaySnapshot *);
    const VtEntry *e;

    ReplaySnapshot_BeginNamedSection(s, "AIActionPtr");
    ReplaySnapshot_MoveChar(s, &have, 1);
    if (have != 0) {
        if (a != NULL)
            type = a->Type;
        ReplaySnapshot_MoveData(s, &type, 1, -1, 0);
        if (s->RestoringSnapshotFlag) {
            switch ((uint32_t)type) {
            case AIACTION_PASS:
                a = &aipass_init(aiaction_new(), 0, 0.0f, NULL, 0.0f)->Base;
                break;
            case AIACTION_AVOID_CARS:
                a = &aiavoidcars_init(aiaction_new(), 0, 0.0f, NULL, 0.0f,
                                      0, 0)->Base;
                break;
            case AIACTION_DRAFT:
                a = &aidraft_init(aiaction_new(), 0, 0.0f)->Base;
                break;
            case AIACTION_BLOCK:
                a = &aiblock_init(aiaction_new(), 0, 0.0f, NULL)->Base;
                break;
            case AIACTION_NUDGE_CAR:
                a = &ainudgecar_init(aiaction_new(), 0, 0.0f, NULL)->Base;
                break;
            case AIACTION_JUST_DRIVE:
                a = &aijustdrive_init(aiaction_new(), 0, 0.0f)->Base;
                break;
            case AIACTION_PULL_OVER:
                a = &aipullover_init(aiaction_new(), 0, 0.0f, 0.0f, NULL,
                                     NULL)->Base;
                break;
            case AIACTION_GET_UNSTUCK:
                a = &aigetunstuck_init(aiaction_new(), 0, 0.0f, -1.0f)->Base;
                break;
            case AIACTION_AVOID_ROADBLOCK:
                a = &aiavoidroadblock_init(aiaction_new(), 0, 0.0f,
                                           NULL)->Base;
                break;
            case AIACTION_I_JUST_GOT_HIT:
                a = &aijustgothit_init(aiaction_new(), 0, 0.0f, NULL)->Base;
                break;
            case AIACTION_ACCIDENT_RECOVERY:
                a = &aiaccidentrecovery_init(aiaction_new(), 0, 0.0f)->Base;
                break;
            default:
                break;
            }
            *pp = a;
        }
        if (a != NULL) {
            e = vt_slot(a->Base._vtable, AIACTION_VT_DO_SNAPSHOT);
            ((SnapFn)e->fn)(vt_this(a, e), s);
        }
    }
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// Retail 0x002b7b10.
static const VtEntry aijustdrive_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aijustdrive_destroy),                     //   8  0x001ca7f8
    E(aijustdrive_do_snapshot),              //  16  0x001c7400
    E(aijustdrive_calculate_points_to_drive),   //  24  0x001c74b8
    E(aijustdrive_get_name),                    //  32  0x001ca7e8
    E(aijustdrive_has_been_accomplished),       //  40  0x001c7460
    E(aijustdrive_has_failed),                  //  48  0x001c74b0
    E(aijustdrive_has_expired),                 //  56  0x001c7468
};

// Retail 0x002b7bd0. GetName is AIAction's.
static const VtEntry aidraft_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aidraft_destroy),                         //   8  0x001ca918
    E(aidraft_do_snapshot),                  //  16  0x001c76d0
    E(aidraft_calculate_points_to_drive),       //  24  0x001c77a8
    E(aiaction_get_name),                       //  32  0x001caae0
    E(aidraft_has_been_accomplished),           //  40  0x001c7750
    E(aidraft_has_failed),                      //  48  0x001c77a0
    E(aidraft_has_expired),                     //  56  0x001c7758
};

// Retail 0x002b7b90. GetName is AIAction's.
static const VtEntry ainudgecar_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(ainudgecar_destroy),                      //   8  0x001ca8b8
    E(ainudgecar_do_snapshot),               //  16  0x001c8078
    E(ainudgecar_calculate_points_to_drive),    //  24  0x001c8150
    E(aiaction_get_name),                       //  32  0x001caae0
    E(ainudgecar_has_been_accomplished),        //  40  0x001c80e8
    E(ainudgecar_has_failed),                   //  48  0x001c8148
    E(ainudgecar_has_expired),                  //  56  0x001c80f0
};

// Retail 0x002b7b50. GetName is AIAction's.
static const VtEntry aiblock_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiblock_destroy),                         //   8  0x001ca858
    E(aiblock_do_snapshot),                  //  16  0x001c81b0
    E(aiblock_calculate_points_to_drive),       //  24  0x001c8288
    E(aiaction_get_name),                       //  32  0x001caae0
    E(aiblock_has_been_accomplished),           //  40  0x001c8220
    E(aiblock_has_failed),                      //  48  0x001c8280
    E(aiblock_has_expired),                     //  56  0x001c8228
};

// Retail 0x002b79d0.
static const VtEntry aiaccidentrecovery_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiaccidentrecovery_destroy),              //   8  0x001ca5c8
    E(aiaccidentrecovery_do_snapshot),       //  16  0x001ca240
    E(aiaccidentrecovery_calculate_points_to_drive), // 24  0x001ca438
    E(aiaccidentrecovery_get_name),             //  32  0x001ca5b8
    E(aiaccidentrecovery_has_been_accomplished), // 40  0x001ca398
    E(aiaccidentrecovery_has_failed),           //  48  0x001ca430
    E(aiaccidentrecovery_has_expired),          //  56  0x001ca3e8
};

// Retail 0x002b7c10.
static const VtEntry aipass_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aipass_destroy),                          //   8  0x001ca988
    E(aipass_do_snapshot),                   //  16  0x001c7960
    E(aipass_calculate_points_to_drive),        //  24  0x001c7ea8
    E(aipass_get_name),                         //  32  0x001ca978
    E(aipass_has_been_accomplished),            //  40  0x001c7b90
    E(aipass_has_failed),                       //  48  0x001c7d48
    E(aipass_has_expired),                      //  56  0x001c7d00
};

// Retail 0x002b7c50.
static const VtEntry aiavoidcars_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiavoidcars_destroy),                     //   8  0x001caa00
    E(aiavoidcars_do_snapshot),              //  16  0x001c6c48
    E(aiavoidcars_calculate_points_to_drive),   //  24  0x001c6ef8
    E(aiavoidcars_get_name),                    //  32  0x001ca9f0
    E(aiavoidcars_has_been_accomplished),       //  40  0x001c6e78
    E(aiavoidcars_has_failed),                  //  48  0x001c6ef0
    E(aiavoidcars_has_expired),                 //  56  0x001c6ee8
};

// Retail 0x002b7ad0.
static const VtEntry aipullover_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aipullover_destroy),                      //   8  0x001ca788
    E(aipullover_do_snapshot),               //  16  0x001c8370
    E(aipullover_calculate_points_to_drive),    //  24  0x001c86a8
    E(aipullover_get_name),                     //  32  0x001ca778
    E(aipullover_has_been_accomplished),        //  40  0x001c8610
    E(aipullover_has_failed),                   //  48  0x001c8658
    E(aipullover_has_expired),                  //  56  0x001c8650
};

// Retail 0x002b7a10.
static const VtEntry aijustgothit_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aijustgothit_destroy),                    //   8  0x001ca638
    E(aijustgothit_do_snapshot),             //  16  0x001c9cb8
    E(aijustgothit_calculate_points_to_drive),  //  24  0x001c9f60
    E(aijustgothit_get_name),                   //  32  0x001ca628
    E(aijustgothit_has_been_accomplished),      //  40  0x001c9e90
    E(aijustgothit_has_failed),                 //  48  0x001c9f58
    E(aijustgothit_has_expired),                //  56  0x001c9f10
};

// Retail 0x002b7a50.
static const VtEntry aigetunstuck_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aigetunstuck_destroy),                    //   8  0x001ca6a8
    E(aigetunstuck_do_snapshot),             //  16  0x001c8bb8
    E(aigetunstuck_calculate_points_to_drive),  //  24  0x001c9550
    E(aigetunstuck_get_name),                   //  32  0x001ca698
    E(aigetunstuck_has_been_accomplished),      //  40  0x001c9140
    E(aigetunstuck_has_failed),                 //  48  0x001c9340
    E(aigetunstuck_has_expired),                //  56  0x001c9298
};

// Retail 0x002b7a90.
static const VtEntry aiavoidroadblock_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiavoidroadblock_destroy),                //   8  0x001ca718
    E(aiavoidroadblock_do_snapshot),         //  16  0x001c96b8
    E(aiavoidroadblock_calculate_points_to_drive), // 24  0x001c98e0
    E(aiavoidroadblock_get_name),               //  32  0x001ca708
    E(aiavoidroadblock_has_been_accomplished),  //  40  0x001c9858
    E(aiavoidroadblock_has_failed),             //  48  0x001c98d8
    E(aiavoidroadblock_has_expired),            //  56  0x001c98d0
};

#undef E

void aiactions_install_vtables(void)
{
    vt_install(AIJUSTDRIVE_VTABLE, aijustdrive_vt, AIACTION_VT_ENTRIES);
    vt_install(AIDRAFT_VTABLE, aidraft_vt, AIACTION_VT_ENTRIES);
    vt_install(AINUDGECAR_VTABLE, ainudgecar_vt, AIACTION_VT_ENTRIES);
    vt_install(AIBLOCK_VTABLE, aiblock_vt, AIACTION_VT_ENTRIES);
    vt_install(AIACCIDENTRECOVERY_VTABLE, aiaccidentrecovery_vt,
               AIACTION_VT_ENTRIES);
    vt_install(AIPASS_VTABLE, aipass_vt, AIACTION_VT_ENTRIES);
    vt_install(AIAVOIDCARS_VTABLE, aiavoidcars_vt, AIACTION_VT_ENTRIES);
    vt_install(AIPULLOVER_VTABLE, aipullover_vt, AIACTION_VT_ENTRIES);
    vt_install(AIIJUSTGOTHIT_VTABLE, aijustgothit_vt, AIACTION_VT_ENTRIES);
    vt_install(AIGETUNSTUCK_VTABLE, aigetunstuck_vt, AIACTION_VT_ENTRIES);
    vt_install(AIAVOIDROADBLOCK_VTABLE, aiavoidroadblock_vt,
               AIACTION_VT_ENTRIES);
}
