// aidriver -- see aidriver.h and docs/formats/ai-driver.md.
#include "aidriver.h"

#include <math.h>
#include <string.h>

#include "aiactions.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "difficultyinfo.h"
#include "drivingchoice.h"
#include "psychodriver.h"
#include "race.h"
#include "realtime.h"   // WorldTimer
#include "replay.h"
#include "trackpath.h"
#include "vtable.h"
#include "world.h"

int32_t AIActionDraftScore = 200;
int32_t AIActionPassScore = 300;
int32_t AIActionNudgeCarScore = 300;
int32_t AIActionBlockScore = 400;
int32_t AIActionAvoidCarsScore = 400;
int32_t AIActionIJustGotHitScore = 400;
int32_t AIActionGetUnstuckScore = 500;
int32_t AIActionAccidentRecoveryScore = 500;
int32_t AIActionPullOverScore = 600;
int32_t AIActionAvoidRoadBlockScore = 600;

float AIActionPassLifetime = 5.0f;
float AIActionDraftLifetime;
float AIActionNudgeCarLifetime = 5.0f;
float AIActionJustDriveLifetime;
float AIActionBlockLifetime = 5.0f;
float AIActionGetUnstuckLifetime = 5.0f;
float AIActionPullOverLifetime;
float AIActionAvoidCarsLifetime;
float AIActionIJustGotHitLifetime;
float AIActionAccidentRecoveryLifetime;

float AIActionPullOverTrafficCarTimeout = -999.0f;
float AIActionPullOverCrossFinishLineTimeout = 15.0f;
float AIActionPullOverStoppedByCopsTimeout = 3.0f;

float AIDriverFrictionBoost = 1.0f;

// The constructor's and Think's VeryStuckProgressTimer (gp-32044 and
// gp-32040, 6000.5 already in ticks, `cvt.w.s` to 6000): 1.5 s.
#define AID_PROGRESS_SECONDS 1.5f

// ShouldWeAvoidThisCar forgets the car not to avoid after a second (`lui
// 0x3f80`, `c.le.s`); GetUnstuck waits 6 s since the last action that
// wasn't (`lui 0x40c0`, `c.lt.s`).
#define AID_NOT_AVOID_SECONDS 1.0f
#define AID_UNSTUCK_WAIT      6.0f

// gp-32036 and gp-32020: a tick in seconds.
#define AID_TICKS_TO_SECONDS 0.000250000012f

// A very stuck car's GetUnstuck lasts at least 1.6 s (gp-32028): the
// progress average full and under 0.2 (gp-32032), the car off the road.
#define AID_VERY_STUCK_PROGRESS 0.200000003f
#define AID_VERY_STUCK_LIFETIME 1.60000002f

// Every action's lifetime but the forced ones' and Pass's and AvoidCars'
// (`lui 0xbf80`), and GetUnstuck's minimum lifetime unless very stuck.
#define AID_NO_LIFETIME (-1.0f)

// The forced PullOver's PullOverTimeout afterwards (gp-32024).
#define AID_PULL_OVER_TIMEOUT 10000000.0f

// SkillLevel's careful driver, read as 0.
#define AID_CAREFUL_SKILL (-2)

// The Average's slots, and the two bMallocs' pool.
#define AID_PROGRESS_SLOTS 5
#define AID_POOL           CAR_MEMORY_POOL

typedef void  (*DriverDtorFn)(void *self, int32_t flags);
typedef float (*OutOfBoundsFn)(void *self);

// Seconds since `t`: `WorldTimer - t` as a signed word, converted, times
// the tick.
static float seconds_since(const Timer *t)
{
    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)
           * AID_TICKS_TO_SECONDS;
}

// AISkillLevel[skill].CollisionAvoidanceChance with the skill as it is:
// retail forms 380 + 28 * skill from TheDifficultyInfo with no clamp.
static float collision_avoidance_chance(int32_t skill)
{
    return *(const float *)(const void *)(
        (const char *)&TheDifficultyInfo
        + offsetof(DifficultyInfo, AISkillLevel)
        + (ptrdiff_t)sizeof(SkillLevelEntry) * skill
        + offsetof(SkillLevelEntry, CollisionAvoidanceChance));
}

// -------------------------------------------------------------- the record

AIDriver *aidriver_init(AIDriver *d, Car *car)
{
    // 0x0012ffc8.
    PsychoDriver *pd;
    Average *a;

    aicarcontroller_init(&d->Base, car);
    // The two Timers' constructors.
    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;
    d->VeryStuckProgressTimer.PackedTime = 0;
    d->Base.Base._vtable = AIDRIVER_VTABLE;
    pd = (PsychoDriver *)bMalloc((int)sizeof(PsychoDriver), "PsychoDriver",
                                 0, AID_POOL);
    pd = psychodriver_init(pd, car);
    d->Base.CurrentAction = NULL;
    d->CarToPurposefullyNotAvoid = NULL;
    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;
    d->Base.Base.Driver = &pd->Base;
    a = (Average *)bMalloc((int)sizeof(Average),
                           "Very Stuck Progress Average", 0, AID_POOL);
    d->pVeryStuckProgress = average_init(a, AID_PROGRESS_SLOTS);
    timer_set_time(&d->VeryStuckProgressTimer, AID_PROGRESS_SECONDS);
    car_set_friction_boost(car, AIDriverFrictionBoost);
    return d;
}

CarController *aidriver_construct(void *mem, Car *car)
{
    return &aidriver_init((AIDriver *)mem, car)->Base.Base;
}

void aidriver_destroy(AIDriver *d, int32_t flags)
{
    // 0x00130090. Freed and not cleared: nothing reads them again.
    CarDriver *drv;

    d->Base.Base._vtable = AIDRIVER_VTABLE;
    drv = d->Base.Base.Driver;
    if (drv != NULL) {
        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);
        ((DriverDtorFn)e->fn)(vt_this(drv, e), 3);
    }
    if (d->pVeryStuckProgress != NULL)
        average_destroy(d->pVeryStuckProgress, 3);
    aicarcontroller_destroy(&d->Base, flags);
}

// ---------------------------------------------------------------- Think

void aidriver_think(AIDriver *d, float dt)
{
    // 0x00130188.
    car_set_friction_boost(d->Base.Base.pCar, AIDriverFrictionBoost);
    if (timer_is_valid(&d->VeryStuckProgressTimer)
        && !timer_count_down(&d->VeryStuckProgressTimer, dt)) {
        Car *car = d->Base.Base.pCar;

        timer_set_time(&d->VeryStuckProgressTimer, AID_PROGRESS_SECONDS);
        average_record(d->pVeryStuckProgress,
                       TheTrackPathManager.TrackLength
                           * fabsf(car->pRacingCar->dCurrentLapNumberExact));
    }
    // A `j`, not through the table.
    aicarcontroller_think(&d->Base, dt);
}

void aidriver_get_route_numbers_to_use(AIDriver *d, int32_t *first,
                                       int32_t *last)
{
    // 0x00130890.
    (void)d;
    *first = 0;
    *last = 49;
}

// ----------------------------------------------------------- the actions

int aidriver_should_we_avoid_this_car(AIDriver *d, Car *car, float secs)
{
    // 0x001307b0.
    int32_t skill;
    float r;

    (void)secs;
    if (AID_NOT_AVOID_SECONDS
        <= seconds_since(&d->StartTimeForPurposefullyNotAvoidingCar))
        d->CarToPurposefullyNotAvoid = NULL;
    if (car == d->CarToPurposefullyNotAvoid)
        return 0;
    r = world_random_f(pCurrentWorld, 1.0f);
    // `xor` and `movz`: -2 is 0, and anything else is as it is.
    skill = d->Base.Base.pCar->MyDriver->SkillLevel;
    if (skill == AID_CAREFUL_SKILL)
        skill = 0;
    if (r < collision_avoidance_chance(skill))
        return 1;
    d->CarToPurposefullyNotAvoid = car;
    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime =
        (uint32_t)WorldTimer;
    return 0;
}

// Each `new` is bOMalloc from AIActionSlotPool, inline, with no test.
static AIAction *new_get_unstuck(int32_t score, float timeout,
                                 float minLifetime)
{
    return &aigetunstuck_init((AIActionGetUnstuck *)aiaction_new(), score,
                              timeout, minLifetime)->Base;
}

static AIAction *new_pull_over(AIDriver *d, float pullOverTimeout)
{
    return &aipullover_init((AIActionPullOver *)aiaction_new(),
                            AIActionPullOverScore, AIActionPullOverLifetime,
                            pullOverTimeout, d->Base.CurrentNearbyCarList,
                            d->Base.CurrentDrivingLocation)->Base;
}

static AIAction *new_forced(AIDriver *d, AIActionType type)
{
    // The switch on type - 2 (the table at 0x002ae300): 3, 4, 8 and 9,
    // and anything under 2 or over 10, have no case of their own.
    switch (type) {
    case AIACTION_DRAFT:
        return &aidraft_init((AIActionDraft *)aiaction_new(),
                             AIActionDraftScore, AIActionDraftLifetime)->Base;
    case AIACTION_JUST_DRIVE:
        return &aijustdrive_init((AIActionJustDrive *)aiaction_new(),
                                 AIActionJustDriveScore,
                                 AIActionJustDriveLifetime)->Base;
    case AIACTION_PULL_OVER: {
        AIAction *a = new_pull_over(d, d->Base.PullOverTimeout);

        d->Base.PullOverTimeout = AID_PULL_OVER_TIMEOUT;
        return a;
    }
    case AIACTION_GET_UNSTUCK:
        return new_get_unstuck(AIActionGetUnstuckScore,
                               AIActionGetUnstuckLifetime, AID_NO_LIFETIME);
    case AIACTION_ACCIDENT_RECOVERY:
        return &aiaccidentrecovery_init(
                   (AIActionAccidentRecovery *)aiaction_new(),
                   AIActionAccidentRecoveryScore,
                   AIActionAccidentRecoveryLifetime)->Base;
    default:
        return new_pull_over(d, AIActionPullOverStoppedByCopsTimeout);
    }
}

// Whether to try the action of `type` and `score` against the current
// one: not the same type, and no lower score.
static int worth_trying(AIActionType type, int32_t score,
                        AIActionType curType, int32_t curScore)
{
    return type != curType && !(score < curScore);
}

// GetUnstuck's minimum lifetime: 1.6 s for a car off the road whose
// progress average is full and under 0.2, else none.
static float unstuck_min_lifetime(AIDriver *d)
{
    CarController *b = &d->Base.Base;
    const VtEntry *e = vt_slot(b->_vtable,
                               CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS);
    const Average *a;

    if (!(0.0f < ((OutOfBoundsFn)e->fn)(vt_this(b, e))))
        return AID_NO_LIFETIME;
    a = d->pVeryStuckProgress;
    if (a->nSamples == a->nSlots && a->fAverage < AID_VERY_STUCK_PROGRESS)
        return AID_VERY_STUCK_LIFETIME;
    return AID_NO_LIFETIME;
}

void aidriver_choose_new_action(AIDriver *d, AIAction **out,
                                AIActionType type)
{
    // 0x00130238.
    AICarController *c = &d->Base;
    DrivingInformation *info = &c->MyCurrentDrivingInformation;
    DrivingChoice choice;
    const tRoadBlock *rb;
    Car *hitCar, *avoidCar, *passCar;
    float secs, amount;
    int okay, used;
    AIActionType curType = AIACTION_NONE;
    int32_t curScore = -1;
    int32_t s;

    if (type != AIACTION_NONE) {
        *out = new_forced(d, type);
        return;
    }

    // The out slots, as the stack has them, and the choice Cleared.
    okay = 1;
    avoidCar = NULL;
    passCar = NULL;
    hitCar = NULL;
    used = 0;
    secs = 0.0f;
    amount = 0.0f;
    rb = NULL;
    drivingchoice_clear(&choice);
    if (c->CurrentAction != NULL) {
        curScore = c->CurrentAction->Score;
        curType = c->CurrentAction->Type;
    }

    if (worth_trying(AIACTION_GET_UNSTUCK, AIActionGetUnstuckScore, curType,
                     curScore)
        && AID_UNSTUCK_WAIT
               < seconds_since(&c->LastTimeNonGetUnstuckActionWasCalled)) {
        s = aigetunstuck_calculate_score(info);
        if (s >= 0) {
            float minLifetime = unstuck_min_lifetime(d);

            *out = new_get_unstuck(s, AIActionGetUnstuckLifetime,
                                   minLifetime);
            c->LastTimeNonGetUnstuckActionWasCalled.PackedTime =
                (uint32_t)WorldTimer;
            return;
        }
    }

    if (worth_trying(AIACTION_AVOID_ROADBLOCK, AIActionAvoidRoadBlockScore,
                     curType, curScore)) {
        s = aiavoidroadblock_calculate_score(info, &rb);
        if (s >= 0) {
            *out = &aiavoidroadblock_init(
                       (AIActionAvoidRoadBlock *)aiaction_new(), s,
                       AID_NO_LIFETIME, rb)->Base;
            return;
        }
    }

    if (worth_trying(AIACTION_I_JUST_GOT_HIT, AIActionIJustGotHitScore,
                     curType, curScore)) {
        s = aijustgothit_calculate_score(info, &hitCar);
        if (s >= 0) {
            aicarcontroller_maybe_honk_and_or_blink_headlights(
                c, hitCar, c->CurrentNearbyCarList);
            *out = &aijustgothit_init((AIActionIJustGotHit *)aiaction_new(),
                                      s, AID_NO_LIFETIME, hitCar)->Base;
            return;
        }
    }

    if (worth_trying(AIACTION_AVOID_CARS, AIActionAvoidCarsScore, curType,
                     curScore)) {
        s = aiavoidcars_calculate_score(info, &avoidCar, &choice, &secs,
                                        &okay, &used);
        if (s >= 0) {
            aicarcontroller_maybe_honk_and_or_blink_headlights(
                c, avoidCar, c->CurrentNearbyCarList);
            if (aidriver_should_we_avoid_this_car(d, avoidCar, secs)) {
                info->MyDrivingChoice = choice;
                // Retail's arguments, one place on: the bool `okay`
                // (converted unsigned) as the seconds, `used` as okay, and
                // 0 as usedPreferred.
                *out = &aiavoidcars_init(
                           (AIActionAvoidCars *)aiaction_new(), s,
                           AIActionAvoidCarsLifetime, avoidCar,
                           (float)(uint32_t)okay, used, 0)->Base;
                return;
            }
        }
    }

    if (worth_trying(AIACTION_ACCIDENT_RECOVERY,
                     AIActionAccidentRecoveryScore, curType, curScore)) {
        s = aiaccidentrecovery_calculate_score(info);
        if (s >= 0) {
            *out = &aiaccidentrecovery_init(
                       (AIActionAccidentRecovery *)aiaction_new(), s,
                       AID_NO_LIFETIME)->Base;
            return;
        }
    }

    if (worth_trying(AIACTION_PASS, AIActionPassScore, curType, curScore)) {
        s = aipass_calculate_score(info, &passCar, &choice, &amount);
        if (s >= 0
            && aidriver_should_we_avoid_this_car(d, passCar,
                                                 AID_NO_LIFETIME)) {
            info->MyDrivingChoice = choice;
            *out = &aipass_init((AIActionPass *)aiaction_new(), s,
                                AIActionPassLifetime, passCar, amount)->Base;
            return;
        }
    }

    // JustDrive is tried whatever the current action.
    s = aijustdrive_calculate_score(info);
    if (s >= 0)
        *out = &aijustdrive_init((AIActionJustDrive *)aiaction_new(), s,
                                 AID_NO_LIFETIME)->Base;
}

// ------------------------------------------------------------ the replay

void aidriver_do_snapshot(AIDriver *d, ReplaySnapshot *s)
{
    // 0x00130108. Every field: the car by its driver number, both timers
    // and the Average.
    ReplaySnapshot_BeginNamedSection(s, "AIDriver");
    aicarcontroller_do_snapshot(&d->Base, s);
    world_do_car_pointer_snapshot(pCurrentWorld, &d->CarToPurposefullyNotAvoid,
                                  s);
    ReplaySnapshot_MoveTimer(s, (int32_t *)&d->StartTimeForPurposefullyNotAvoidingCar.PackedTime);
    ReplaySnapshot_MoveTimer(s, (int32_t *)&d->VeryStuckProgressTimer.PackedTime);
    average_do_snapshot(d->pVeryStuckProgress, s);
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$8AIDriver, retail's 0x002ae328.
static const VtEntry aidriver_vt[AICARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aidriver_destroy),                              //   8  0x00130090
    E(aicarcontroller_debug_display),                 //  16  0x00191138
    E(aidriver_do_snapshot),                          //  24  0x00130108
    E(aidriver_think),                                //  32  0x00130188
    E(aicarcontroller_set_current_route),             //  40  0x00190670
    E(aicarcontroller_get_current_route),             //  48  0x00190708
    E(aicarcontroller_get_current_route_point),       //  56  0x00190760
    E(aicarcontroller_get_amount_out_of_bounds),      //  64  0x001907b8
    E(aicarcontroller_find_where_i_am),               //  72  0x00192f10
    E(aicarcontroller_just_reset),                    //  80  0x00190850
    E(aicarcontroller_set_to_physics_mode),           //  88  0x00193650
    E(aicarcontroller_force_boost),                   //  96  0x00193758
    E(aicarcontroller_release_boost),                 // 104  0x00193780
    E(aidriver_get_route_numbers_to_use),             // 112  0x00130890
    E(aidriver_choose_new_action),                    // 120  0x00130238
    E(aicarcontroller_generate_points_to_fulfill_action), // 128  0x00192668
};

#undef E

void aidriver_install_vtables(void)
{
    vt_install(AIDRIVER_VTABLE, aidriver_vt, AICARCONTROLLER_VT_ENTRIES);
}
