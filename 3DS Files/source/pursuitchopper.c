// pursuitchopper -- the helicopter's side of a chase. See pursuitchopper.h.

#include "pursuitchopper.h"

#include <math.h>
#include <stddef.h>

#include "car.h"
#include "chopper.h"
#include "copmanager.h"
#include "playerinit.h"
#include "pursuit.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"
#include "world.h"

void (*gSpeechRaiseRotorRequestFn)(uint32_t speaker, int32_t supervisor);
void (*gSpeechRaiseRotorConfirmFn)(void);
void (*gSpeechRaiseDispatchHelicopterNAFn)(uint32_t speaker);

#define SUPERVISOR_NEAR        0.001f      // gp-27068
#define REQUEST_TIME           10.0f       // lui 0x4120
#define CONFIRM_TIME           5.0f        // lui 0x40a0
#define ATTACK_TIME            15.0f       // lui 0x4170
#define NEXT_ATTACK_STEP       2.0f        // lui 0x4000
#define NEXT_ATTACK_MIN        6.0f        // lui 0x40c0
#define NEAR_CAR               200.0f      // lui 0x4348

// The behaviours UpdateChopper reads: 0x20 a helicopter asked for, then
// what its attacks may be.
#define BEHAVE_CHOPPER         0x20u
#define BEHAVE_SMOKE_BOMB_2    0x40u
#define BEHAVE_SPIKE_BELT      0x80u
#define BEHAVE_ROCKET          0x100u
#define BEHAVE_BEACOP_CHOPPER  0x1e0u
#define BEHAVE_ROAD_BLOCK      0x8u
#define BEHAVE_BEACOP_ROAD     0x18u

int32_t tcopmanager_is_chopper_available(const tCopManager *m)
{
    struct Chopper *h = pCurrentWorld->Helicopter;

    if (h == NULL || TheRaceParameters.New624 == 0 || h->New960 != 0)
        return 0;
    return m->bChopperBusy == 0;
}

struct Chopper *tcopmanager_request_chopper(tCopManager *m)
{
    struct Chopper *h = pCurrentWorld->Helicopter;

    if (h == NULL || TheRaceParameters.New624 == 0 || m->bChopperBusy != 0)
        return NULL;
    if (TheRaceParameters.BeACop != 0 && m->nBeACopNumChopperAttacks == 0)
        return NULL;
    m->bChopperBusy = 1;
    if (m->nBeACopNumChopperAttacks != 0)
        m->nBeACopNumChopperAttacks--;
    return h;
}

// GetInGameSample's sample, played at full volume.
static void play_sample(const char *name)
{
    struct bSample *s = gGetInGameSampleFn != NULL ? gGetInGameSampleFn(name)
                                                   : NULL;

    if (s != NULL && gSamplePlayFn != NULL)
        gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);
}

// The player cop's chase. Retail reads Cops[nPlayerCopIndex]'s first word
// with no test; Be A Cop always has the cop, and the port's NULL is no
// chase.
static tPursuit *player_cop_pursuit(tCopManager *m)
{
    tCop *c = copmanager_get_player_cop(m);

    return c != NULL ? c->pMyPursuit : NULL;
}

void tcopmanager_be_a_cop_request_chopper(tCopManager *m)
{
    tPursuit   *p = player_cop_pursuit(m);
    const char *name = "BeACopRequestFailed";

    if (p != NULL && p->pChopper == NULL
        && (p->BehaviourFlags & BEHAVE_CHOPPER) == 0) {
        p->BehaviourFlags |= BEHAVE_BEACOP_CHOPPER;
        if (m->nBeACopNumChopperAttacks != 0)
            name = "BeACopRequestOk";
    }
    play_sample(name);
}

void tcopmanager_be_a_cop_request_road_block(tCopManager *m)
{
    tPursuit   *p = player_cop_pursuit(m);
    const char *name = "BeACopRequestFailed";

    if (p != NULL && p->pRoadBlock == NULL
        && (p->BehaviourFlags & BEHAVE_ROAD_BLOCK) == 0) {
        p->BehaviourFlags |= BEHAVE_BEACOP_ROAD;
        if (m->nBeACopNumRoadBlocks != 0)
            name = "BeACopRequestOk";
    }
    play_sample(name);
}

// ATTACKING's next attack: a smoke bomb, unless the chase allows a spike
// belt or a rocket on a car with its tyres whole and World::Random says
// so; a rocket never twice running. The chase that allows the second
// smoke bomb picks between the two.
static ChopperAttackType pick_attack(tPursuit *p)
{
    uint32_t flags = p->BehaviourFlags;
    int32_t  whole = (int8_t)p->pChasedCar->BlownTireBits == 0;

    if ((flags & BEHAVE_SPIKE_BELT) != 0 && whole
        && world_random_i(pCurrentWorld, 2) == 0)
        return CHOPATTACK_SPIKE_BELT;
    if (p->pChopper->BombRunType != CHOPATTACK_ROCKET
        && (flags & BEHAVE_ROCKET) != 0 && whole
        && world_random_i(pCurrentWorld, 2) == 0)
        return CHOPATTACK_ROCKET;
    if ((flags & BEHAVE_SMOKE_BOMB_2) != 0)
        return world_random_i(pCurrentWorld, 2) != 0
            ? CHOPATTACK_SMOKE_BOMB_2 : CHOPATTACK_SMOKE_BOMB_1;
    return CHOPATTACK_SMOKE_BOMB_1;
}

void tpursuit_update_chopper(tPursuit *p)
{
    if (p->pChopper != NULL) {
        if (p->pChopper->New960 != 0)
            return;
    } else if ((p->BehaviourFlags & BEHAVE_CHOPPER) != 0
               && tcopmanager_is_chopper_available(pCopManager)) {
        uint32_t spk = tpursuit_get_cop_speaker(p);
        int32_t  sup = fabsf(pCopManager->fSupervisorTimer) <= SUPERVISOR_NEAR;

        if (gSpeechRaiseRotorRequestFn != NULL)
            gSpeechRaiseRotorRequestFn(spk, sup);
        p->ChopperState = ECS_CHOPPER_REQUESTED;
        p->fChopperAttackTimer = REQUEST_TIME;
        p->pChopper = tcopmanager_request_chopper(pCopManager);
        if (p->pChopper != NULL)
            p->pChopper->TotalSalvos = 0;
        if (TheRaceParameters.BeACop != 0)
            p->BehaviourFlags &= ~BEHAVE_CHOPPER;
    }
    if (p->ChopperState == ECS_NO_CHOPPER)
        return;
    if (p->fChaseDirection == -1.0f
        && p->ChopperState != ECS_CHOPPER_REQUESTED) {
        chopper_abort_bombing_run(p->pChopper);
        p->ChopperState = ECS_CHOPPER_INFLIGHT;
        p->fChopperAttackTimer = REQUEST_TIME;
    }
    p->fChopperAttackTimer -= WorldTimeElapsed;
    if (!(p->fChopperAttackTimer < 0.0f))
        return;
    switch (p->ChopperState) {
    case ECS_CHOPPER_REQUESTED:
        if (p->pChopper != NULL) {
            if (gSpeechRaiseRotorConfirmFn != NULL)
                gSpeechRaiseRotorConfirmFn();
            p->ChopperState = ECS_CHOPPER_INFLIGHT;
            p->fChopperAttackTimer = CONFIRM_TIME;
        } else if (TheRaceParameters.BeACop != 0) {
            if (gSpeechRaiseDispatchHelicopterNAFn != NULL)
                gSpeechRaiseDispatchHelicopterNAFn(pCopManager->BeACopId);
            p->ChopperState = ECS_NO_CHOPPER;
        }
        break;
    case ECS_CHOPPER_INFLIGHT:
        p->fChopperAttackTimer = ATTACK_TIME;
        p->ChopperState = ECS_CHOPPER_ATTACKING;
        chopper_follow_this_car(p->pChopper, p->pChasedCar);
        break;
    case ECS_CHOPPER_ATTACKING: {
        float             next = p->fChopperNextAttackTime;
        ChopperAttackType type;

        p->fChopperAttackTimer = next;
        p->fChopperNextAttackTime = next - NEXT_ATTACK_STEP;
        if (p->fChopperNextAttackTime < NEXT_ATTACK_MIN)
            p->fChopperNextAttackTime = NEXT_ATTACK_MIN;
        type = pick_attack(p);
        if (p->pChopper->CurrentCar != p->pChasedCar)
            chopper_follow_this_car(p->pChopper, p->pChasedCar);
        else
            chopper_attack_car(p->pChopper, type);
        break;
    }
    default:
        break;
    }
}

int32_t tpursuit_is_chopper_near_car(const tPursuit *p)
{
    const struct Chopper *h = p->pChopper;
    const struct Car     *car;
    float                 dx, dy;

    if (p->ChopperState != ECS_CHOPPER_ATTACKING || h == NULL)
        return 0;
    car = p->pChasedCar;
    dy = h->CurrentPos.y - car->State.Position.y;
    dx = h->CurrentPos.x - car->State.Position.x;
    return sqrtf(dx * dx + dy * dy) < NEAR_CAR;
}

int32_t pursuitchopper_new960(struct Chopper *h)
{
    return h->New960;
}

void pursuitchopper_follow_this_car(struct Chopper *h, struct Car *car)
{
    (void)chopper_follow_this_car(h, car);
}
