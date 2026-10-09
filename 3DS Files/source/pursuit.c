// pursuit -- tPursuit. See pursuit.h.

#include "pursuit.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "barricade.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinfo.h"
#include "cartypeinfo.h"
#include "cop.h"
#include "copdriver.h"
#include "copmgr.h"
#include "coputil.h"
#include "drivetarget.h"
#include "hudscore.h"
#include "playerhud.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "table.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

float fRoadBlockSpawnTime;

// 0x002bd320, which the constructor copies to its stack: the roadblock
// spawn time by the manager's difficulty.
static const float fRoadBlockSpawnTimes[3] = { 20.0f, 15.0f, 10.0f };

// 0x0031c570: each state's seconds, before the race's length scales them.
static const float fPursuitStateTimes[6] = {
    30.0f, 20.0f, 40.0f, 300.0f, 10.0f, 100000.0f
};

void (*gPursuitStartSpeechFn)(tPursuit *p);
void (*gPursuitJoinSpeechFn)(tPursuit *p);
void (*gPursuitBackOffSpeechFn)(tPursuit *p);
void (*gSpeechRaiseCrashTowFn)(uint32_t was, uint32_t now);
void (*gSpeechRaiseCrashFn)(uint32_t was, uint32_t now);
void (*gSpeechRaiseFlatTireFn)(uint32_t was, uint32_t now);
void (*gSpeechRaiseSuperRequestFn)(uint32_t speaker);
int32_t (*gChopperNew960Fn)(struct Chopper *c);
void    (*gChopperFollowThisCarFn)(struct Chopper *c, struct Car *car);
void (*gPursuitDeclareSpeechFn)(tPursuit *p);
void (*gPursuitRaiseBackupSpeechFn)(tPursuit *p);
void (*gPursuitBeginCollisionSpeechFn)(tPursuit *p, struct Car *hit);
void (*gSpeechRaisePursuitCopHitFn)(uint32_t speaker, int32_t where);
void (*gSpeechRaiseSuspectCrashTrafficFn)(uint32_t speaker, int32_t b);
void (*gCopManagerCreatePulloverFn)(tCopManager *m, tPursuit *p,
                                    struct Car *car, int32_t b);
void (*gPursuitCreateRoadBlockFn)(tPursuit *p);
void (*gPursuitUpdateRoadBlocksFn)(tPursuit *p);
void (*gPursuitUpdateChopperFn)(tPursuit *p);

// fCopCaptureRadius, gp-15592: 10.0, which nothing writes.
#define PURSUIT_CAPTURE_RADIUS  10.0f

// 0x0031c588: the speed under which the cops catch a Be A Cop car, by the
// manager's difficulty: 20, 15 and 15 mph.
static const float fBeACopCatchSpeeds[3] = {
    8.940545082092285f, 6.705409049987793f, 6.705409049987793f
};

#define PURSUIT_MPH  2.236999988555908f

typedef void    (*DtorFn)(void *self, int32_t flags);
typedef int32_t (*IsAIControlledFn)(void *self);

static void unported(const char *name)
{
    fprintf(stderr, "pursuit: %s is not ported\n", name);
    abort();
}

// ------------------------------------------------- the small records

tPursuitHistory *tpursuithistory_construct(tPursuitHistory *h)
{
    int32_t i;

    h->vptr = TPURSUITHISTORY_VTABLE;
    for (i = 0; i < 30; i++) {
        h->v2Velocity[i].x = 0.0f;
        h->v2Velocity[i].y = 0.0f;
        h->fTime[i] = 0.0f;
    }
    h->nCount = 0;
    return h;
}

void tpursuithistory_destruct(tPursuitHistory *h, int32_t flags)
{
    h->vptr = TPURSUITHISTORY_VTABLE;
    if (flags & 1)
        bFree(h);
}

tRoadBlockStateMachine *trbsm_construct(tRoadBlockStateMachine *s,
                                        tPursuit *p)
{
    s->pPursuit = p;
    s->State = ERBS_NONE;
    s->SpeechFlags = 0;
    s->nRoadBlockCount = 0;
    return s;
}

void trbsm_destruct(tRoadBlockStateMachine *s, int32_t flags)
{
    if (flags & 1)
        bFree(s);
}

void trbsm_disband_road_block(tRoadBlockStateMachine *s)
{
    s->State = ERBS_NONE;
}

// ------------------------------------------------------ GetTopSpeed
float get_top_speed(Car *car)
{
    const CarTypeInfo *ti = car->pCarTypeInfo;
    float              v = 27.77777862548828f;

    while (v < 111.11111450195312f) {
        float a = table_get_value(get_acceleration_table(car->pRideInfo->Type),
                                  v);

        if (a < v * v * ti->Aero.Drag / ti->Body.Mass)
            break;
        v = v + 1.388888955116272f;
    }
    return v - 1.388888955116272f;
}

// ------------------------------------------------------- tPursuit

// ReserveCopSpeaker from the constructor. From an empty queue retail's
// returns its a2, which here still holds the first two words of the
// constructor's copy of {20, 15, 10}: the speaker is 20.0f's bits.
static uint32_t reserve_speaker_in_ctor(void)
{
    const CopSpeakerDeque *d = &pCopManager->CopSpeakers;

    if (d->Full == 0 && d->Tail == d->Head)
        return 0x41a00000u;
    return copmanager_reserve_cop_speaker(pCopManager);
}

tPursuit *tpursuit_construct(tPursuit *p, int8_t id, Car *car)
{
    p->vptr = TPURSUIT_VTABLE;
    p->pChasedCar = car;
    drivetarget_init(&p->FarDriveTarget);
    drivetarget_init(&p->NearDriveTarget);
    tpursuithistory_construct(&p->History);
    trbsm_construct(&p->RoadBlockStateMachine, p);
    p->nPursuitId = id;
    p->nNumCops = 0;
    p->nHUDPursuitLevel = 0;
    p->nRoadblockCount = 0;
    p->fCatchCarTimer = 2.0f;
    p->fRoadBlockDisbandTimer = 3.5f;
    fRoadBlockSpawnTime = fRoadBlockSpawnTimes[pCopManager->nDifficultyLevel];
    p->fRoadBlockSpawnTimer = 0.0f;
    p->fChopperAttackTimer = 10.0f;
    p->fChopperNextAttackTime = 12.0f;
    p->SecondaryCopSpeaker = COP_SPEAKER_NONE;
    p->Cops[1] = NULL;
    p->Cops[0] = NULL;
    p->CurrentLandmark = 0;
    p->bAlreadyJoined = 0;
    p->bAlreadyBeenHit = 0;
    p->bAlreadyCalledForBackup = 0;
    p->pRoadBlock = NULL;
    p->BehaviourFlags = 0;
    p->pChopper = NULL;
    p->ChopperState = ECS_NO_CHOPPER;
    // With no chased car, or an AI one outside Be A Cop, retail leaves
    // PrimaryCopSpeaker as the slot held it.
    if (p->pChasedCar != NULL) {
        p->fChasedCarTopSpeed = get_top_speed(p->pChasedCar);
        if (TheRaceParameters.BeACop != 0)
            p->PrimaryCopSpeaker = pCopManager->BeACopId;
        else if (p->pChasedCar->pPlayer != NULL)
            p->PrimaryCopSpeaker = reserve_speaker_in_ctor();
    }
    if (pRaceCoordinator->CurrentRCState == RCSTATE_AI_DEMO_MODE)
        tpursuit_switch_state(p, EPS_LEVEL3);
    else
        tpursuit_switch_state(p, EPS_LEVEL0);
    p->fChaseDirectionTimer = 0.0f;
    p->fChaseDirection = 1.0f;
    p->pBarricades = barricademanager_construct(
        (BarricadeManager *)bMalloc((int)sizeof(BarricadeManager), "CopMgr",
                                    0, 16));
    p->New1556 = 10.0f;
    return p;
}

void tpursuit_destruct(tPursuit *p, int32_t flags)
{
    p->vptr = TPURSUIT_VTABLE;
    tpursuit_release_all_cops(p);
    if (p->pChasedCar->pPlayer != NULL) {
        copmanager_release_cop_speaker(pCopManager, p->PrimaryCopSpeaker);
        if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE)
            copmanager_release_cop_speaker(pCopManager,
                                           p->SecondaryCopSpeaker);
    }
    p->nPursuitId = -2;
    if (p->pBarricades != NULL) {
        BarricadeManager *b = p->pBarricades;
        const VtEntry    *e = vt_slot(b->vptr, BARRICADEMANAGER_VT_DTOR);

        ((DtorFn)e->fn)(vt_this(b, e), 3);
    }
    trbsm_destruct(&p->RoadBlockStateMachine, 2);
    tpursuithistory_destruct(&p->History, 2);
    drivetarget_destroy(&p->NearDriveTarget);
    drivetarget_destroy(&p->FarDriveTarget);
    // bTNode<tPursuit>'s destructor, with 0, does nothing.
    if (flags & 1)
        bSlotFree(PursuitSlotPool, p);
}

float tpursuit_state_time(float f)
{
    float laps = 1.0f;
    float len;

    if (TheRaceParameters.Point2Point == 0)
        laps = (float)TheRaceParameters.NumLapsInRace;
    len = laps * TheTrackPathManager.TrackLength;
    if (42000.0f < len)
        len = 42000.0f;
    if (len < 14000.0f)
        len = 14000.0f;
    return f * (len * 1.7857142665889114e-05f + 0.25f);
}

void tpursuit_switch_state(tPursuit *p, ePursuitState s)
{
    Player *pl = NULL;
    Car    *car;

    p->PursuitState = s;
    p->fPursuitStateTimer = tpursuit_state_time(fPursuitStateTimes[s]);
    if (p->pChasedCar != NULL)
        pl = p->pChasedCar->pPlayer;
    switch (p->PursuitState) {
    case EPS_LEVEL0:
        p->nHUDPursuitLevel = 1;
        p->PursuitSubState = LSS_NONE;
        p->BehaviourFlags |= 0x2u;
        break;
    case EPS_LEVEL1:
        p->BehaviourFlags |= 0x3u;
        p->PursuitSubState = LSS_PURSUIT_FOLLOW;
        p->bAlreadyCalledForBackup = 1;
        p->nHUDPursuitLevel = 2;
        break;
    case EPS_LEVEL2:
        p->BehaviourFlags |= 0x7u;
        p->bAlreadyCalledForBackup = 1;
        p->nHUDPursuitLevel = 3;
        p->PursuitSubState = LSS_FOLLOW_OFFSET;
        copmanager_possible_call_supervisor(pCopManager, p);
        break;
    case EPS_LEVEL3:
        p->BehaviourFlags |= 0x20fu;
        p->bAlreadyCalledForBackup = 1;
        p->nHUDPursuitLevel = 4;
        p->PursuitSubState = LSS_FOLLOW_BACKWARDS;
        copmanager_possible_call_supervisor(pCopManager, p);
        break;
    case EPS_SPEEDER_CAUGHT:
        p->nHUDPursuitLevel = 0;
        break;
    case EPS_END_PURSUIT_GIVE_UP:
        p->nHUDPursuitLevel = 0;
        if (pl != NULL) {
            if (gPursuitBackOffSpeechFn != NULL)
                gPursuitBackOffSpeechFn(p);
            player_start_score(pl, SCORING_BEAT_THE_COPS);
        }
        car = p->pChasedCar;
        pCopManager->fPursuableTimer[car->CarIndex] = 999999.0f;
        pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] = 999999.0f;
        tpursuit_release_all_cops(p);
        break;
    default:
        break;
    }
}

int32_t tpursuit_do_state_transition(tPursuit *p)
{
    ePursuitState s = p->PursuitState;
    ePursuitState to = EPS_LEVEL3;
    int32_t       over = 0;

    switch (s) {
    case EPS_LEVEL0:
        to = EPS_LEVEL1;
        break;
    case EPS_LEVEL1:
        to = EPS_LEVEL2;
        break;
    case EPS_LEVEL2:
    case EPS_LEVEL3:
        to = EPS_LEVEL3;
        break;
    case EPS_SPEEDER_CAUGHT:
        to = EPS_SPEEDER_CAUGHT;
        break;
    case EPS_END_PURSUIT_GIVE_UP:
        over = 1;
        break;
    default:
        break;
    }
    if (to != s && !over)
        tpursuit_switch_state(p, to);
    return over;
}

float tpursuit_get_speed_mph_or_kph(const tPursuit *p)
{
    const Car *car = p->pChasedCar;
    float      v = car->State.ForwardSpeed;

    if (car->pPlayer != NULL
        && TheRaceParameters.GlobalDisplaySettings.Units != 0)
        return v * 3.5999999046325684f;
    return v * 2.236999988555908f;
}

// 0x0022a310: the helicopter let go, unless its word at 960 holds it.
static void release_chopper(tPursuit *p)
{
    if (p->pChopper == NULL)
        return;
    if (gChopperNew960Fn == NULL || gChopperFollowThisCarFn == NULL)
        unported("the pursuit's chopper (12k)");
    if (gChopperNew960Fn(p->pChopper) != 0)
        return;
    pCopManager->bChopperBusy = 0;
    gChopperFollowThisCarFn(p->pChopper, NULL);
    p->ChopperState = ECS_NO_CHOPPER;
    p->pChopper = NULL;
}

void tpursuit_release_all_cops(tPursuit *p)
{
    int32_t i;

    for (i = 0; i < p->nNumCops; i++) {
        tCop          *c = p->Cops[i];
        const VtEntry *e;

        if (c == NULL)
            continue;
        tpursuit_remove_cop_from_pursuit(p, c);
        e = vt_slot(c->vptr, TCOP_VT_IS_AI_CONTROLLED);
        if (((IsAIControlledFn)e->fn)(vt_this(c, e)) != 0)
            taicop_return_to_patrol((tAICop *)(void *)c);
    }
    tpursuit_disband_road_block(p, 0);
    release_chopper(p);
}

void tpursuit_disband_road_block(tPursuit *p, int32_t b)
{
    int32_t i;

    if (p->pRoadBlock == NULL)
        return;
    for (i = 0; i < 2; i++) {
        tCop *c = (tCop *)(void *)p->pRoadBlock->cops[i];

        if (c == NULL)
            continue;
        tpursuit_remove_cop_from_pursuit(p, c);
        taicop_return_to_patrol((tAICop *)(void *)c);
        if (b) {
            Car  *ch = p->pChasedCar;
            Car  *mine = c->pMyCar;
            float dx = ch->State.Position.x - mine->State.Position.x;
            float dy = ch->State.Position.y - mine->State.Position.y;

            if (sqrtf(dx * dx + dy * dy) < 30.0f
                && copmanager_request_pursuit(pCopManager, c, ch) != 0)
                tcop_set_desired_logic_state(c, LS_HOT_PURSUIT);
        }
    }
    if (tpursuit_is_player_involved(p)) {
        if (p->pChasedCar->pPlayer != NULL
            && p->SecondaryCopSpeaker == COP_SPEAKER_NONE
            && TheRaceParameters.NumPlayerCars == 1)
            p->SecondaryCopSpeaker = p->pRoadBlock->CopSpeaker;
        else
            copmanager_release_cop_speaker(pCopManager,
                                           p->pRoadBlock->CopSpeaker);
    }
    copmanager_delete_road_block_spike_strips(
        pCopManager, p->pRoadBlock->nIndexIntoLoadedData);
    barricademanager_fade(p->pBarricades, 2.0f);
    p->pRoadBlock = NULL;
    trbsm_disband_road_block(&p->RoadBlockStateMachine);
}

int32_t tpursuit_remove_cop_from_pursuit(tPursuit *p, tCop *c)
{
    int32_t found = 0;
    int32_t i;

    if (c == NULL)
        return 0;
    for (i = 0; i < p->nNumCops; i++) {
        if (p->Cops[i] != c)
            continue;
        p->Cops[i] = NULL;
        p->nNumCops--;
        if (p->Cops[0] == NULL) {
            p->Cops[0] = p->Cops[1];
            p->Cops[1] = NULL;
        }
        found = 1;
        break;
    }
    if (!found && p->pRoadBlock != NULL) {
        tRoadBlock *rb = p->pRoadBlock;

        for (i = 0; i < 2 && !found; i++) {
            if ((tCop *)(void *)rb->cops[i] == c) {
                rb->cops[i] = NULL;
                found = 1;
            }
        }
    }
    if (found)
        tcop_set_pursuit(c, NULL);
    return found;
}

int32_t tpursuit_is_cop_in_pursuit(const tPursuit *p, const tCop *c)
{
    int32_t i;

    for (i = 0; i < p->nNumCops; i++)
        if (p->Cops[i] == c)
            return 1;
    if (p->pRoadBlock != NULL)
        for (i = 0; i < 2; i++)
            if ((const tCop *)(const void *)p->pRoadBlock->cops[i] == c)
                return 1;
    return 0;
}

void tpursuit_remove_primary_speaker(tPursuit *p, int32_t b)
{
    uint32_t was;

    if (p->pChasedCar->pPlayer == NULL)
        return;
    if (tpursuit_road_block_encountered_recently(p))
        return;
    was = p->PrimaryCopSpeaker;
    copmanager_release_cop_speaker(pCopManager, was);
    if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE) {
        p->PrimaryCopSpeaker = p->SecondaryCopSpeaker;
        p->SecondaryCopSpeaker = COP_SPEAKER_NONE;
    } else if (p->nNumCops < 2) {
        p->PrimaryCopSpeaker = p->SecondaryCopSpeaker;
    } else {
        p->PrimaryCopSpeaker = copmanager_reserve_cop_speaker(pCopManager);
    }
    if (b) {
        if ((uint32_t)bRandomI(10, &bDefaultSeed) < 2u) {
            if (gSpeechRaiseCrashTowFn != NULL)
                gSpeechRaiseCrashTowFn(was, p->PrimaryCopSpeaker);
        } else if (gSpeechRaiseCrashFn != NULL) {
            gSpeechRaiseCrashFn(was, p->PrimaryCopSpeaker);
        }
    } else if (gSpeechRaiseFlatTireFn != NULL) {
        gSpeechRaiseFlatTireFn(was, p->PrimaryCopSpeaker);
    }
}

int32_t tpursuit_road_block_encountered_recently(const tPursuit *p)
{
    float t;

    if ((int8_t)p->pChasedCar->BlownTireBits != 0)
        return 1;
    t = fRoadBlockSpawnTime;
    if (p->ChopperState == ECS_CHOPPER_REQUESTED)
        t = t + t;
    return t - 4.0f < p->fRoadBlockSpawnTimer;
}

void tpursuit_select_primary_cop(tPursuit *p)
{
    tCop *a = p->Cops[0];
    tCop *b = p->Cops[1];
    Car  *car, *ca, *cb;
    float dx, dy, da, db;

    if (a == NULL || b == NULL)
        return;
    car = p->pChasedCar;
    ca = a->pMyCar;
    cb = b->pMyCar;
    dy = car->State.Position.y - ca->State.Position.y;
    dx = car->State.Position.x - ca->State.Position.x;
    da = sqrtf(dx * dx + dy * dy);
    dy = car->State.Position.y - cb->State.Position.y;
    dx = car->State.Position.x - cb->State.Position.x;
    db = sqrtf(dx * dx + dy * dy);
    if (30.0f < da - db) {
        p->Cops[1] = a;
        p->Cops[0] = b;
    }
}

uint32_t tpursuit_get_cop_speaker(const tPursuit *p)
{
    if (p->PrimaryCopSpeaker != COP_SPEAKER_NONE)
        return p->PrimaryCopSpeaker;
    if (p->pRoadBlock != NULL)
        return p->pRoadBlock->CopSpeaker;
    return copmanager_get_current_cop_speaker(pCopManager);
}

uint32_t tpursuit_get_secondary_cop_speaker(const tPursuit *p)
{
    if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE)
        return p->SecondaryCopSpeaker;
    return copmanager_get_current_cop_speaker(pCopManager);
}

int32_t tpursuit_is_player_involved(const tPursuit *p)
{
    return p->pChasedCar->pPlayer != NULL || TheRaceParameters.BeACop != 0;
}

// ---------------------------------------------------- the one-liners

void tpursuit_add_cop(tPursuit *p, tCop *c)
{
    p->Cops[p->nNumCops] = c;
    p->nNumCops++;
}

int32_t tpursuit_get_num_cops(const tPursuit *p)
{
    return p->nNumCops;
}

int32_t tpursuit_get_pursuit_id(const tPursuit *p)
{
    return p->nPursuitId;
}

eRoadBlockState tpursuit_get_road_block_state(const tPursuit *p)
{
    return p->RoadBlockStateMachine.State;
}

float tpursuit_get_chase_direction(const tPursuit *p)
{
    return p->fChaseDirection;
}

eChopperState tpursuit_get_chopper_state(const tPursuit *p)
{
    return p->ChopperState;
}

int32_t tpursuit_is_pursuit_over(const tPursuit *p)
{
    return p->PursuitState == EPS_END_PURSUIT_GIVE_UP;
}

int32_t tpursuit_has_called_for_backup(const tPursuit *p)
{
    return p->bAlreadyCalledForBackup;
}

int32_t tpursuit_is_backup_needed(const tPursuit *p)
{
    if (p->nNumCops == 0)
        return 1;
    return p->nNumCops < p->nMaxChaseCops && p->bAlreadyCalledForBackup != 0;
}

tCop *tpursuit_get_other_cop(const tPursuit *p, const tCop *c)
{
    return p->Cops[0] == c ? p->Cops[1] : p->Cops[0];
}

int32_t tpursuit_is_primary_car(const tPursuit *p, const Car *car)
{
    return p->Cops[0] != NULL && p->Cops[0]->pMyCar == car;
}

int32_t tpursuit_is_primary(const tPursuit *p, const tCop *c)
{
    return p->Cops[0] == c;
}

int32_t tpursuit_is_behaviour_allowed(const tPursuit *p, uint32_t a)
{
    return (int32_t)(p->BehaviourFlags & a);
}

void tpursuit_disallow_all_behaviours(tPursuit *p)
{
    p->BehaviourFlags = 0;
}

void tpursuit_disallow_behaviour(tPursuit *p, uint32_t a)
{
    p->BehaviourFlags &= ~a;
}

void tpursuit_allow_behaviour(tPursuit *p, uint32_t a)
{
    p->BehaviourFlags |= a;
}

int32_t tpursuit_get_current_landmark(const tPursuit *p)
{
    return p->CurrentLandmark;
}

int32_t tpursuit_get_pursuit_level_for_hud(const tPursuit *p)
{
    return p->nHUDPursuitLevel;
}

// --------------------------------------------------------- the Update

void tpursuit_level0_sub_states(tPursuit *p)
{
    if (p->PursuitSubState == 0) {
        if (p->fPursuitStateTimer < 16.0f) {
            if (gPursuitDeclareSpeechFn != NULL)
                gPursuitDeclareSpeechFn(p);
            p->PursuitSubState = 1;
        }
    } else if (p->PursuitSubState == 1) {
        if (p->fPursuitStateTimer < 3.0f) {
            if (gPursuitRaiseBackupSpeechFn != NULL)
                gPursuitRaiseBackupSpeechFn(p);
            p->PursuitSubState = 2;
        }
    }
}

int32_t tpursuit_should_pursuit_be_called_off(const tPursuit *p)
{
    const Car *car = p->pChasedCar;
    float      left;

    if ((int8_t)car->BlownTireBits != 0)
        return 0;
    if (TheRaceParameters.Point2Point != 0)
        return 0;
    if (race_parameters_is_free_run(&TheRaceParameters))
        return 0;
    if (TheRaceParameters.NumLapsInRace < 4)
        return 0;
    left = (float)TheRaceParameters.NumLapsInRace
           - car->pRacingCar->FinishedLapNumberExact;
    return left * TheTrackPathManager.TrackLength <= 2000.0f;
}

void tpursuithistory_update(tPursuitHistory *h, bVector2 *out,
                            const bVector2 *pos, const bVector2 *vel,
                            float dt)
{
    int32_t i;

    for (i = 29; i > 0; i--) {
        h->v2Velocity[i] = h->v2Velocity[i - 1];
        h->fTime[i] = h->fTime[i - 1];
    }
    h->v2Velocity[0].x = vel->x;
    h->v2Velocity[0].y = vel->y;
    h->fTime[0] = dt;
    if (h->nCount != 30)
        h->nCount++;
    *out = *pos;
}

// The two targets' step: the position as a new point once the last two
// are `apart` or more apart (`strict`: more), the oldest dropped at 20,
// else over the last point.
static void follow_target(DriveTarget *t, const bVector2 *pos, float apart,
                          int strict)
{
    int32_t n = t->NumPoints;

    if (n >= 2) {
        const bVector3 *a = &t->Points[n - 1];
        const bVector3 *b = &t->Points[n - 2];
        float dx = b->x - a->x;
        float dy = b->y - a->y;
        float d = sqrtf(dx * dx + dy * dy);

        if (strict ? !(apart < d) : !(apart <= d)) {
            drivetarget_set_point2(t, n - 1, pos, -1, -1, -1, 0.0f);
            return;
        }
        if (n == 20)
            drivetarget_shift_left(t, 1, 1);
    }
    drivetarget_add_point2(t, pos, -1, -1, -1, 0, NULL);
}

void tpursuit_update_drive_targets(tPursuit *p, float dt)
{
    Car     *car = p->pChasedCar;
    bVector2 pos;
    bVector2 out;

    (void)dt;
    pos.x = car->State.Position.x;
    pos.y = car->State.Position.y;
    follow_target(&p->FarDriveTarget, &pos, 20.0f, 0);
    car = p->pChasedCar;
    tpursuithistory_update(&p->History, &out,
                           (const bVector2 *)(const void *)
                               &car->State.Position,
                           (const bVector2 *)(const void *)
                               &car->State.Velocity,
                           WorldTimeElapsed);
    follow_target(&p->NearDriveTarget, &pos, 1.0f, 1);
}

void trbsm_update(tRoadBlockStateMachine *s)
{
    if (s->State == ERBS_NONE)
        return;
    s->fStateTimer -= WorldTimeElapsed;
    if (s->fStateTimer <= 0.0f)
        s->fStateTimer = 0.0f;
    if (s->State != ERBS_CALLED_FOR_ROAD_BLOCK || s->fStateTimer != 0.0f)
        return;
    if (gPursuitCreateRoadBlockFn != NULL)
        gPursuitCreateRoadBlockFn(s->pPursuit);
    if (s->pPursuit->pRoadBlock != NULL)
        s->State = ERBS_ROAD_BLOCK_SET;
}

void tpursuit_do_early_chase_collision_check(tPursuit *p)
{
    Car     *hit;
    uint32_t s;

    if (p->pChasedCar->pPlayer == NULL || p->bAlreadyBeenHit != 0)
        return;
    hit = car_caused_recent_collision(p->pChasedCar);
    if (hit == NULL)
        return;
    p->bAlreadyBeenHit = 1;
    if (p->PursuitSubState == 0) {
        if (gPursuitBeginCollisionSpeechFn != NULL)
            gPursuitBeginCollisionSpeechFn(p, hit);
        return;
    }
    if (p->Cops[0] != NULL && hit == p->Cops[0]->pMyCar) {
        s = tpursuit_get_cop_speaker(p);
        if (gSpeechRaisePursuitCopHitFn != NULL)
            gSpeechRaisePursuitCopHitFn(s, p->CurrentLandmark);
        tpursuit_switch_state(p, EPS_LEVEL2);
        return;
    }
    if (hit->MyDriver->TheDriverType == DRIVER_TYPE_COP) {
        tpursuit_switch_state(p, EPS_LEVEL2);
        return;
    }
    s = tpursuit_get_cop_speaker(p);
    if (gSpeechRaiseSuspectCrashTrafficFn != NULL)
        gSpeechRaiseSuspectCrashTrafficFn(s, 0);
    if (p->PursuitState == EPS_LEVEL0)
        tpursuit_switch_state(p, EPS_LEVEL1);
}

static float distance_2d(const Car *a, const Car *b)
{
    float dx = a->State.Position.x - b->State.Position.x;
    float dy = a->State.Position.y - b->State.Position.y;

    return sqrtf(dx * dx + dy * dy);
}

int32_t copmanager_is_cop_nearby(tCopManager *m, Car *car, float d)
{
    int32_t found = 0;
    int32_t i;

    if (TheRaceParameters.BeACop != 0) {
        tCop *pc = copmanager_get_player_cop(m);

        if (pc == NULL)
            return 0;
        return distance_2d(pc->pMyCar, car) <= d;
    }
    for (i = 0; i < m->nNumCops && !found; i++) {
        Car *cc;

        switch (m->Cops[i]->DesiredLogicState) {
        case LS_DISABLED:
        case LS_SPEED_TRAP:
        case LS_ROAD_BLOCK:
        case LS_DRIVING_ON_PATROL:
        case LS_HOT_PURSUIT:
        case LS_GUARD_LOCATION:
            break;
        default:
            continue;
        }
        cc = m->Cops[i]->pMyCar;
        if (cc->pPlayer != NULL && player_is_nis_playing(cc->pPlayer))
            continue;
        if (distance_2d(cc, car) <= d)
            found = 1;
    }
    return found;
}

int32_t copmanager_did_recently_collide_with_cop(tCopManager *m, Car *car)
{
    int32_t hit = 0;
    int32_t i;

    for (i = 0; i < m->nNumCops && !hit; i++)
        if (did_these_cars_collide(car, m->Cops[i]->pMyCar))
            hit = 1;
    return hit;
}

// On its side or over (the body's up axis 0.1 or less upright) and under
// 10 mph.
static int32_t is_upset(const Car *car)
{
    return car->State.BodyMatrix.v2.z <= 0.10000000149011612f
           && car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f;
}

// Be A Cop's half. Retail reads the player's cop through NULL when there
// is none; the port says the car cannot be stopped.
static int32_t be_a_cop_stoppable(tPursuit *p, Car *car)
{
    tCop   *pc = copmanager_get_player_cop(pCopManager);
    float   d, radius, slow;
    int32_t stop = 0;
    int32_t timing = 1;

    if (pc == NULL)
        return 0;
    d = distance_2d(car, pc->pMyCar);
    if (car_is_blinking(car)
        && (car->pPlayer != NULL ? car->JustResetFrames != 0 : d < 30.0f)) {
        stop = 1;
    } else {
        radius = PURSUIT_CAPTURE_RADIUS;
        if (TheRaceParameters.NumPlayerCars == 2)
            radius = radius * 1.100000023841858f;
        if (d < radius) {
            if ((int8_t)car->BlownTireBits != 0
                && car->State.VelocityMagnitude < 0.10000000149011612f) {
                stop = 1;
            } else if (is_upset(car)) {
                stop = 1;
            } else {
                slow = fBeACopCatchSpeeds[pCopManager->nDifficultyLevel];
                if (TheRaceParameters.NumPlayerCars == 2)
                    slow = slow * 1.5f;
                if (car->State.VelocityMagnitude < slow) {
                    timing = 0;
                    p->fCatchCarTimer -= WorldTimeElapsed;
                    if (p->fCatchCarTimer < 0.0f)
                        stop = 1;
                }
            }
        }
    }
    if (stop)
        return pc->pMyCar->State.VelocityMagnitude < 6.705409049987793f;
    if (timing) {
        p->fCatchCarTimer += WorldTimeElapsed;
        if (2.0f < p->fCatchCarTimer)
            p->fCatchCarTimer = 2.0f;
    }
    return 0;
}

int32_t tpursuit_is_chased_car_stoppable(tPursuit *p)
{
    Car                    *car = p->pChasedCar;
    const tCarPulloverInfo *pl;
    int32_t                 stop = 0;
    int32_t                 near;

    if (TheRaceParameters.bTickets == 0)
        return 0;
    pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)pCopManager + COPMANAGER_PULLOVERS);
    if (pl[car->CarIndex].bActive != 0)
        return 0;
    if (car_is_poofed(car))
        return 0;
    if (car->pRacingCar->FinishReason != 0)
        return 0;
    if (TheRaceParameters.BeACop != 0)
        return be_a_cop_stoppable(p, car);

    if (p->New1556 <= 0.0f)
        stop = 1;
    if (p->Cops[0] != NULL)
        near = copmanager_is_cop_nearby(pCopManager, car,
                                        PURSUIT_CAPTURE_RADIUS);
    else
        near = car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER;
    if (car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f && near) {
        p->fCatchCarTimer -= WorldTimeElapsed;
        if (p->fCatchCarTimer <= 0.0f)
            stop = 1;
        else if (p->fCatchCarTimer <= 1.0f
                 && copmanager_did_recently_collide_with_cop(pCopManager,
                                                             car))
            stop = 1;
    } else {
        p->fCatchCarTimer = 2.0f;
    }
    if ((int8_t)car->BlownTireBits != 0
        && car->State.VelocityMagnitude < 0.10000000149011612f)
        return 1;
    if (car_is_blinking(car)
        && (car->pPlayer == NULL || car->JustResetFrames != 0))
        return 1;
    if (is_upset(car))
        stop = 1;
    return stop;
}

// Be A Cop with two players: the way the chased car is going along its
// route, which the chase takes once the car has gone 8 s against it.
static void update_chase_direction(tPursuit *p, Car *car)
{
    const TrackRoutePoint *rp = car_get_route_point(car, 1);
    float dot = car->State.Velocity.x * rp->Direction.x
                + car->State.Velocity.y * rp->Direction.y;
    float dir = 0.0f <= dot ? 1.0f : -1.0f;

    if (0.0f < dir * p->fChaseDirection) {
        p->fChaseDirectionTimer = 0.0f;
        return;
    }
    p->fChaseDirectionTimer += WorldTimeElapsed;
    if (8.0f <= p->fChaseDirectionTimer) {
        p->fChaseDirectionTimer = 0.0f;
        p->fChaseDirection = dir;
    }
}

int32_t tpursuit_update(tPursuit *p)
{
    Car      *car;
    Landmark *lm;
    int32_t   over = 0;
    int32_t   i;

    barricademanager_count_down(p->pBarricades, WorldTimeElapsed);
    lm = copmgr_find_landmark((const bVector2 *)(const void *)
                                  &p->pChasedCar->State.Position);
    p->CurrentLandmark = lm != NULL ? lm->LandmarkType : 0;
    car = p->pChasedCar;
    if ((int8_t)car->BlownTireBits != 0)
        p->New1556 -= WorldTimeElapsed;
    if (TheRaceParameters.NumPlayerCars != 1
        && car->pRacingCar->FinishReason != 0)
        return 1;
    if (TheRaceParameters.BeACop != 0) {
        if (TheRaceParameters.NumPlayerCars == 2)
            update_chase_direction(p, car);
    } else {
        if (p->fChasedCarTopSpeed < car->State.ForwardSpeed)
            p->fChasedCarTopSpeed = car->State.ForwardSpeed;
        for (i = 0; i < p->nNumCops; i++) {
            Car *cc = p->Cops[i]->pMyCar;

            if (cc->TheMovementMode == COP_MOVEMENT)
                ((CopMover *)(void *)cc->pCarMover)->fBaseMaxSpeed =
                    p->fChasedCarTopSpeed;
        }
        tpursuit_update_drive_targets(p, WorldTimeElapsed);
        tpursuit_select_primary_cop(p);
        if (TheRaceParameters.RaceType == 3)
            over = p->pChasedCar->pRacingCar->FinishReason != 0;
        if (tpursuit_should_pursuit_be_called_off(p)) {
            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);
            over = 1;
        } else if (p->nNumCops != 0 || p->PursuitState >= EPS_LEVEL3) {
            p->fPursuitStateTimer -= WorldTimeElapsed;
        }
        if (p->fPursuitStateTimer <= 0.0f && tpursuit_do_state_transition(p))
            over = 1;
    }
    if (!tpursuit_not_in_chasing_state(p)) {
        if (over)
            return over;
        if (tpursuit_is_chased_car_stoppable(p)) {
            if (gCopManagerCreatePulloverFn != NULL)
                gCopManagerCreatePulloverFn(pCopManager, p, p->pChasedCar, 1);
            over = 1;
            tpursuit_switch_state(p, EPS_SPEEDER_CAUGHT);
            tpursuit_release_all_cops(p);
        }
    }
    if (over)
        return over;
    trbsm_update(&p->RoadBlockStateMachine);
    if (gPursuitUpdateRoadBlocksFn != NULL)
        gPursuitUpdateRoadBlocksFn(p);
    if (gPursuitUpdateChopperFn != NULL)
        gPursuitUpdateChopperFn(p);
    if (TheRaceParameters.BeACop != 0)
        return 0;
    switch (p->PursuitState) {
    case EPS_LEVEL0:
        tpursuit_level0_sub_states(p);
        tpursuit_do_early_chase_collision_check(p);
        return 0;
    case EPS_LEVEL1:
        tpursuit_do_early_chase_collision_check(p);
        return 0;
    case EPS_END_PURSUIT_GIVE_UP:
        return 1;
    default:
        return 0;
    }
}

// --------------------------------------- tCopManager's, making pursuits

tPursuit *copmanager_new_pursuit(tCopManager *m, int32_t id, Car *car)
{
    tPursuit     *p = (tPursuit *)bSlotOMalloc(PursuitSlotPool);
    tPursuitNode *list = &m->PursuitList;
    tPursuitNode *tail;

    tpursuit_construct(p, (int8_t)id, car);
    tail = list->Prev;
    tail->Next = &p->Node;
    if ((int8_t)id >= 0)
        m->PursuitsById[(int8_t)id] = p;
    list->Prev = &p->Node;
    p->Node.Prev = tail;
    p->Node.Next = list;
    return p;
}

void (*gPlayerLoadNextNisFn)(Player *pl, Car *chased, Car *cop,
                             int32_t tickets);

int32_t copmanager_request_pursuit(tCopManager *m, tCop *c, Car *car)
{
    tPursuit *p = NULL;
    int32_t   found = 0;
    int32_t   ai = 0;
    int32_t   maxChase = 0;
    int32_t   maxBlock = 0;
    int32_t   ok = 0;

    if (car->pRacingCar->FinishReason != 0)
        return 0;
    if (TheRaceParameters.BeACop != 0) {
        if (c == copmanager_get_player_cop(m)) {
            maxChase = 1;
            maxBlock = 2;
            ok = 1;
        }
    } else {
        tPursuitNode *n;

        for (n = m->PursuitList.Next; n != &m->PursuitList; n = n->Next) {
            tPursuit *q = (tPursuit *)(void *)n;

            if (q->pChasedCar->pPlayer == NULL)
                ai++;
            if (q->pChasedCar == car) {
                found = 1;
                p = q;
            }
        }
        if (p != NULL && p->PursuitState == EPS_END_PURSUIT_GIVE_UP)
            return 0;
        if (TheRaceParameters.NumPlayerCars >= 2) {
            maxChase = 1;
            if (car->pPlayer != NULL) {
                maxBlock = 1;
                ok = found ? p->nNumCops < 1 : 1;
            } else {
                maxBlock = 0;
                ok = found ? p->nNumCops < 1 : ai == 0;
            }
        } else if (car->pPlayer != NULL) {
            maxChase = pCurrentWorld->CopCarPos < 3 ? 2 : 1;
            maxBlock = 2;
            if (!found || p->nNumCops == 0)
                ok = 1;
            else
                ok = p->nNumCops < maxChase
                     && p->bAlreadyCalledForBackup != 0;
        } else {
            maxChase = 1;
            maxBlock = 0;
            // The demo disc's build allowed one AI chase, not two.
            ok = found ? p->nNumCops < 1 : ai < 2;
        }
    }
    if (!ok)
        return 0;
    if (!found) {
        Player *pl;

        p = copmanager_new_pursuit(m, copmanager_find_free_pursuit_id(m),
                                   car);
        if (gPursuitStartSpeechFn != NULL)
            gPursuitStartSpeechFn(p);
        pl = (TheRaceParameters.BeACop != 0 ? c->pMyCar
                                             : p->pChasedCar)->pPlayer;
        if (pl != NULL) {
            Car    *mine = c->pMyCar;
            int32_t tickets = copmanager_get_num_tickets(m, p->pChasedCar);

            if (gPlayerLoadNextNisFn != NULL)
                gPlayerLoadNextNisFn(pl, p->pChasedCar, mine, tickets);
        }
    } else if (gPursuitJoinSpeechFn != NULL) {
        gPursuitJoinSpeechFn(p);
    }
    p->nMaxChaseCops = maxChase;
    p->nMaxRoadBlockCops = maxBlock;
    p->Cops[p->nNumCops] = c;
    p->nNumCops++;
    tcop_set_pursuit(c, p);
    return ok;
}

void copmanager_possible_call_supervisor(tCopManager *m, tPursuit *p)
{
    if (copmanager_replaying())
        return;
    if (!(fabsf(m->fSupervisorTimer - -50.0f) <= 0.0010000000474974513f))
        return;
    if (TheRaceParameters.bRoadBlocks == 0)
        return;
    if (p->pChasedCar->pPlayer == NULL)
        return;
    if (bRandomI(2, &bDefaultSeed) != 0)
        return;
    {
        uint32_t s = tpursuit_get_cop_speaker(p);

        if (gSpeechRaiseSuperRequestFn != NULL)
            gSpeechRaiseSuperRequestFn(s);
    }
    m->fSupervisorTimer = 7.0f;
}

// ----------------------------------------------------------- the tables

static void tpursuit_dtor_entry(void *self, int32_t flags)
{
    tpursuit_destruct((tPursuit *)self, flags);
}

static void tpursuithistory_dtor_entry(void *self, int32_t flags)
{
    tpursuithistory_destruct((tPursuitHistory *)self, flags);
}

static const VtEntry tpursuit_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tpursuit_dtor_entry },        // 8  0x00229198
};

static const VtEntry tpursuithistory_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tpursuithistory_dtor_entry }, // 8  0x0022cf68
};

void pursuit_install_vtables(void)
{
    vt_install(TPURSUIT_VTABLE, tpursuit_vt,
               (int)(sizeof tpursuit_vt / sizeof tpursuit_vt[0]));
    vt_install(TPURSUITHISTORY_VTABLE, tpursuithistory_vt,
               (int)(sizeof tpursuithistory_vt / sizeof tpursuithistory_vt[0]));
}
