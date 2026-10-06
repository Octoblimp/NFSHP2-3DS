// aiactions -- see aiactions.h.
//
// Written from retail's listing. Every float expression keeps the image's
// association.

#include "aiactions.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "drivetarget.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "realtime.h"   // WorldTimer
#include "topology.h"
#include "vtable.h"

// Retail's constants: AIAction.obj's .lit4 and the few built with `lui`.
#define AIA_TICKS_TO_SECONDS   0.000250000012f  // gp-28708 and the rest
#define AIJD_REEVALUATE_EVERY  3.0f             // lui 0x4040
#define AIJD_NO_HIT            99999.0f         // gp-28700
#define AIDR_CLOSE             6.0f             // lui 0x40c0
#define AIDR_GAP               20.0f            // lui 0x41a0
#define AIAR_UPRIGHT           0.707000017f     // gp-28544, gp-28540
#define AIAR_RESET_AFTER       5.0f             // lui 0x40a0

#define AIDR_SCORE   200
#define AINC_SCORE   300
#define AIBL_SCORE   400
#define AIAR_SCORE   500
#define AIA_NO_SCORE (-1)

float AIDriverAvoidCarsImpactTimeThreshold = 2.0f;

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
}
