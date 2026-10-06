// aiactions -- see aiactions.h.
//
// Written from retail's listing. Every float expression keeps the image's
// association.

#include "aiactions.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "carcollisionpredict.h"
#include "cardriver.h"
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
#include "topology.h"
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

#define AIDR_SCORE   200
#define AINC_SCORE   300
#define AIPA_SCORE   300
#define AIBL_SCORE   400
#define AIAC_SCORE   400
#define AIIJ_SCORE   400
#define AIAR_SCORE   500
#define AIPO_SCORE   600
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

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }
#define PENDING { 0, 0, NULL }

// Retail 0x002b7b10.
static const VtEntry aijustdrive_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aijustdrive_destroy),                     //   8  0x001ca7f8
    PENDING,                                    //  16  DoSnapshot 0x001c7400
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
    PENDING,                                    //  16  DoSnapshot 0x001c76d0
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
    PENDING,                                    //  16  DoSnapshot 0x001c8078
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
    PENDING,                                    //  16  DoSnapshot 0x001c81b0
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
    PENDING,                                    //  16  DoSnapshot 0x001ca240
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
    PENDING,                                    //  16  DoSnapshot 0x001c7960
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
    PENDING,                                    //  16  DoSnapshot 0x001c6c48
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
    PENDING,                                    //  16  DoSnapshot 0x001c8370
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
    PENDING,                                    //  16  DoSnapshot 0x001c9cb8
    E(aijustgothit_calculate_points_to_drive),  //  24  0x001c9f60
    E(aijustgothit_get_name),                   //  32  0x001ca628
    E(aijustgothit_has_been_accomplished),      //  40  0x001c9e90
    E(aijustgothit_has_failed),                 //  48  0x001c9f58
    E(aijustgothit_has_expired),                //  56  0x001c9f10
};

#undef PENDING
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
}
