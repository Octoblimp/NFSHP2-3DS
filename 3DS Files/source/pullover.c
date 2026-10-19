// pullover -- see pullover.h.

#include "pullover.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "aiaction.h"
#include "aicarcontroller.h"
#include "airoute.h"
#include "car.h"
#include "carcontroller.h"
#include "cop.h"
#include "copmgr.h"
#include "hudnis.h"
#include "hudscore.h"
#include "nisoverlay.h"
#include "player.h"
#include "playercam.h"
#include "playerhud.h"
#include "pursuit.h"
#include "race.h"
#include "racefinish.h"
#include "raceparams.h"
#include "raceupdate.h"
#include "realdriver.h"
#include "vtable.h"
#include "world.h"

typedef int32_t (*IsAIControlledFn)(void *self);
typedef void    (*ReleaseBoostFn)(void *self);

int32_t (*gPlayerPlayNextNisFn)(struct Player *pl, struct Car *car,
                                struct Car *cop, void (*done)(int32_t),
                                int32_t param);
void (*gSpeechRaiseRacerCaughtFn)(uint32_t speaker, uint32_t n,
                                  int32_t arrestType);
void (*gSpeechPulloverEventFn)(void);
void (*gSpeechBeACopArrestFn)(int32_t players, int32_t a, int32_t b,
                              int32_t arrests);
void (*gPursuitAITicketSpeechFn)(tPursuit *p);

// The hold without a NIS, and under BUSTED!; how long the car is not to be
// chased after; the radar traps' share of their wait (0x3f400000).
#define HOLD_TIME          7.0f
#define BUSTED_HOLD_TIME   2.0f
#define PURSUABLE_TIME     8.0f
#define TRAP_SPAWN_SHARE   0.75f
// An AI racer's pull-over timeouts: none for a pursuit's car, 3 s for a
// spike strip's.
#define NO_TIMEOUT        -1.0f
#define SPIKE_TIMEOUT      3.0f
// The ticketed player's reset speed (gp-22920) and direction.
#define RESET_SPEED       15.0f
#define RESET_DIRECTION    1.0f
// A radar trap a player not in a NIS is this near keeps its cop.
#define TRAP_KEEP_RANGE  250.0f
// TheRaceParameters' TimeTrialTime is in the Timer's 4000ths (gp-27108).
#define TIMER_SECONDS     0.00025f
// raiseRacerCaught's second argument, and its arrest types by the pursuit's
// HUD level.
#define CAUGHT_N           4u
#define CAUGHT_LEVEL       4

static int32_t cop_is_ai(tCop *c)
{
    const VtEntry *e = vt_slot(c->vptr, TCOP_VT_IS_AI_CONTROLLED);

    return ((IsAIControlledFn)e->fn)(vt_this(c, e));
}

// Retail's FixBlownTires, 0x00135120: the rumble and the two counts. The
// demo's (carrace.c) also let a RealDriver off its e-brake stop, which
// EndPullover does itself.
static void fix_blown_tires(Car *c)
{
    c->fBlownTireControllerRumbleTimer = 0.0f;
    c->BlownTireBits = 0;
    c->NumBlownTires = 0;
}

static Car *player_cop_car(tCopManager *m)
{
    return m->Cops[m->nPlayerCopIndex]->pMyCar;
}

// ------------------------------------------------------- the pullover

void copmanager_create_pullover(tCopManager *m, tPursuit *p, Car *car,
                                int32_t b)
{
    int32_t           i = car->CarIndex;
    tCarPulloverInfo *pl = &m->CarPullovers[i];
    tCop             *cop = NULL;
    Player           *player = NULL;

    pl->bActive = 1;
    pl->bPlayNIS = 0;
    pl->bShouldDisplayBustedText = 0;
    if (car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)
        aicarcontroller_force_pull_over(car_ai_controller(car),
                                        p != NULL ? NO_TIMEOUT
                                                  : SPIKE_TIMEOUT);
    if (b != 0) {
        if (TheRaceParameters.BeACop != 0) {
            cop = m->Cops[m->nPlayerCopIndex];
            player = cop->pMyCar->pPlayer;
            if (pCurrentRace->NumRacingCars - 2 == m->nBeACopNumArrestsMade
                || pCurrentWorld->AICarPos == 2) {
                pl->bPlayNIS = 1;
            } else {
                player_start_busted_display(player);
                pl->bShouldDisplayBustedText = 1;
            }
        } else {
            player = car->pPlayer;
            if (player != NULL) {
                cop = copmanager_get_arresting_officer(m, p);
                pl->bPlayNIS = 1;
            }
        }
        if (pCopManager->CarPullovers[i].nNumTickets
            >= TheRaceParameters.nNumTicketsBeforeArrest) {
            if (TheRaceParameters.BeACop != 0) {
                pl->bArrest = 1;
                player = player_cop_car(m)->pPlayer;
                player_start_score(player, SCORING_SPEED_BUSTED);
            } else if (race_parameters_is_free_run(&TheRaceParameters)
                       == 0) {
                pl->bArrest = 1;
            }
        }
    }

    if (pl->bPlayNIS != 0) {
        if (p != NULL) {
            if (gCopSpeechFlushQueueFn != NULL)
                gCopSpeechFlushQueueFn();
            if (pl->bArrest != 0) {
                uint32_t spk = tpursuit_get_cop_speaker(p);

                if (gSpeechRaiseRacerCaughtFn != NULL)
                    gSpeechRaiseRacerCaughtFn(
                        spk, CAUGHT_N,
                        p->nHUDPursuitLevel == CAUGHT_LEVEL ? 1 : 2);
            } else if (gSpeechPulloverEventFn != NULL) {
                gSpeechPulloverEventFn();
            }
        }
        if (cop_is_ai(cop) != 0) {
            if (p != NULL)
                tpursuit_remove_cop_from_pursuit(p, cop);
            tcop_set_desired_logic_state(cop, LS_CAUGHT_SPEEDER);
            pl->nCopIndex = cop->nCopNumber;
        }
        if (gPlayerPlayNextNisFn != NULL)
            gPlayerPlayNextNisFn(player, car, cop->pMyCar,
                                 copmanager_end_pullover_callback, i);
        copmanager_remove_speed_traps_for_car(m, car);
        if (TheRaceParameters.BeACop != 0 && car->pPlayer != NULL)
            player_remove_camera_movers(car->pPlayer);
    } else {
        if (p != NULL && b != 0 && gPursuitAITicketSpeechFn != NULL)
            gPursuitAITicketSpeechFn(p);
        pl->fHoldTimer = pl->bShouldDisplayBustedText != 0
                             ? BUSTED_HOLD_TIME : HOLD_TIME;
        pl->nCopIndex = -1;
    }
    // A byte, `lbu` and `sb`: 127 tickets wrap.
    if (b != 0)
        pl->nNumTickets = (int8_t)(uint8_t)((uint8_t)pl->nNumTickets + 1u);
}

void copmanager_end_pullover(tCopManager *m, int32_t i)
{
    Car              *car = pCurrentWorld->CarTable[i];
    tCarPulloverInfo *pl = &m->CarPullovers[i];
    int32_t           over = 0;

    pl->bActive = 0;
    m->fPursuableTimer[i] = PURSUABLE_TIME;
    m->fSpeedTrapSpawnTimer[i] =
        copmanager_get_base_speed_trap_spawn_time(m) * TRAP_SPAWN_SHARE;
    fix_blown_tires(car);
    if (car->TheControlMode == REAL_CONTROL)
        realdriver_force_ebrake_stop((RealDriver *)(void *)car->pCarDriver,
                                     0.0f);
    if (pl->nCopIndex != -1) {
        tCop *cop = m->Cops[pl->nCopIndex];

        if (cop_is_ai(cop) != 0)
            taicop_done_writing_ticket((tAICop *)(void *)cop);
    }

    if (pl->bArrest != 0) {
        eRaceFinishReason why = RACING_CAR_ARRESTED;
        int32_t           blink = 0, both = 0;

        m->nBeACopNumArrestsMade++;
        if (car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)
            aicarcontroller_force_pull_over(car_ai_controller(car),
                                            NO_TIMEOUT);
        if (TheRaceParameters.BeACop != 0) {
            if (car->pPlayer != NULL) {
                over = 1;
                both = 1;
                why = RACING_CAR_BE_THE_COP_LOST;
            } else {
                over = pCurrentRace->NumRacingCars - 1
                       == m->nBeACopNumArrestsMade;
                blink = over == 0;
                both = over;
            }
        }
        race_finish_car_by_car(pCurrentRace, car, -1, blink, why);
        car->bVisibleOnTrackMap = 0;
        car->DriverRenderingEnabled = 0;
        if (both != 0) {
            Car    *copCar = player_cop_car(m);
            Player *pp = copCar->pPlayer;

            race_finish_car_by_car(pCurrentRace, copCar, -1, 0,
                                   RACING_CAR_BE_THE_COP_WON);
            if (gSpeechBeACopArrestFn != NULL)
                gSpeechBeACopArrestFn(TheRaceParameters.NumPlayerCars, 0, 1,
                                      m->nBeACopNumArrestsMade);
            player_start_score(pp, SCORING_QUOTA_FILLED);
        }
    } else if (car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER) {
        AICarController *ctl = car_ai_controller(car);
        const VtEntry   *e;

        ctl->ForceCurrentAction = AIACTION_JUST_DRIVE;
        e = vt_slot(ctl->Base._vtable, CARCONTROLLER_VT_RELEASE_BOOST);
        ((ReleaseBoostFn)e->fn)(vt_this(ctl, e));
    } else if (car->pPlayer != NULL) {
        NearestRoutePointInfo at;

        at.Route = car_get_route(car, 1);
        at.Point = car_get_route_point(car, 1);
        ai_get_next_route_point(&at);
        // The last bool is 0: only the player's reset button sets
        // JustResetFrames.
        car_reset_to_route_point(car, at.Route, at.Point, RESET_SPEED, 1,
                                 RESET_DIRECTION, 0);
    }

    if (TheRaceParameters.BeACop == 0)
        return;
    {
        Car *copCar = player_cop_car(m);

        if (pl->bShouldDisplayBustedText != 0)
            player_stop_busted_display(copCar->pPlayer);
        if (copCar->CarIndex == i)
            return;
        copCar->TheSirenMode = SIREN_MODE_NONE;
        // A word in retail (`sw zero,2056`), so the three bytes after too.
        copCar->CopLights = 0;
        memset(copCar->_hole2025, 0, sizeof copCar->_hole2025);
        if (over != 0)
            return;
        if (TheRaceParameters.BeACopResetTimerAfterArrest != 0)
            m->fBeACopTime =
                (float)(int32_t)TheRaceParameters.TimeTrialTime.PackedTime
                * TIMER_SECONDS;
        if (car->pPlayer != NULL) {
            copmanager_reset_all_damage(m, car);
            copmanager_reset_all_damage(m, copCar);
        }
    }
}

void copmanager_end_pullover_callback(int32_t i)
{
    copmanager_end_pullover(pCopManager, i);
}

// ------------------------------------------------------------ the cops

tCop *copmanager_get_arresting_officer(tCopManager *m, tPursuit *p)
{
    tCop   *cop = NULL;
    int32_t k;

    if (p != NULL) {
        for (k = 0; k < p->nNumCops && cop == NULL; k++)
            cop = p->Cops[k];
        if (cop == NULL && p->pRoadBlock != NULL)
            for (k = 0; k < 2 && cop == NULL; k++)
                cop = (tCop *)(void *)p->pRoadBlock->cops[k];
    }
    // The cops' states are read without a test for an empty slot.
    for (k = 0; k < m->nNumAICops && cop == NULL; k++) {
        tCop *c = m->Cops[k];

        if (c->DesiredLogicState == LS_SPEED_TRAP
            || c->DesiredLogicState == LS_DRIVING_ON_PATROL)
            cop = c;
    }
    return cop != NULL ? cop : m->Cops[0];
}

void copmanager_remove_speed_traps_for_car(tCopManager *m, Car *car)
{
    int32_t k, j;

    for (k = 0; k < m->nNumAICops; k++) {
        tCop   *cop = m->Cops[k];
        int32_t release = 1;

        if (cop == NULL || cop->DesiredLogicState != LS_SPEED_TRAP)
            continue;
        // Every player is looked at; any one near keeps the cop.
        for (j = 0; j < pCurrentWorld->AICarPos; j++) {
            Car  *pc = pCurrentWorld->CarTable[j];
            float dx, dy;

            if (pc->pPlayer == NULL || player_is_nis_playing(pc->pPlayer))
                continue;
            dx = pc->State.Position.x - cop->pMyCar->State.Position.x;
            dy = pc->State.Position.y - cop->pMyCar->State.Position.y;
            if (sqrtf(dx * dx + dy * dy) < TRAP_KEEP_RANGE)
                release = 0;
        }
        if (release != 0)
            tcop_set_desired_logic_state(cop, LS_LIMBO);
    }
    pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] =
        copmanager_get_base_speed_trap_spawn_time(pCopManager);
}

void taicop_done_writing_ticket(tAICop *c)
{
    if (c->Base.DesiredLogicState == LS_DISABLED)
        return;
    if (c->Base.DesiredLogicState != LS_CAUGHT_SPEEDER)
        tcop_set_desired_logic_state(&c->Base, LS_CAUGHT_SPEEDER);
    c->Base.LogicSubState = LSS_CAUGHTSPEEDER_WAITING;
    c->fSubStateTimer = 10.0f;
}

// ------------------------------------------------------------ BUSTED!

void player_start_busted_display(Player *p)
{
    nisoverlay_start_busted(&p->mFlailerNIS);
}

void player_stop_busted_display(Player *p)
{
    nisoverlay_finish(&p->mFlailerNIS);
}
