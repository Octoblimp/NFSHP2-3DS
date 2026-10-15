// pursuitspeech -- tPursuit's speech. See pursuitspeech.h.

#include "pursuitspeech.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmgr.h"
#include "coputil.h"
#include "pursuit.h"
#include "race.h"
#include "racecoord.h"
#include "speechconv.h"
#include "speechmgr.h"

// The supervisor's on the radio: the manager's fSupervisorTimer within
// 0.001 of 0 (each method has its own 0.001, gp-27036 .. gp-26992).
static int32_t supervisor_on(void)
{
    return fabsf(pCopManager->fSupervisorTimer) <= 0.001f;
}

// The AI and replay demos (the coordinator's states 8 and 9).
static int32_t in_demo(void)
{
    return (uint32_t)(pRaceCoordinator->CurrentRCState
                      - RCSTATE_AI_DEMO_MODE) < 2u;
}

static uint32_t random_below(int32_t n)
{
    return (uint32_t)bRandomI(n, bViewSeed);
}

int32_t tpursuit_get_chased_car_colour(const tPursuit *p)
{
    const RideInfo *ride = p->pChasedCar->pRideInfo;

    return cartypeinfo_get_skin_info(ride->Type, ride->SkinNumber, 1)
        ->PaintType;
}

int32_t tpursuit_get_exact_description(const tPursuit *p)
{
    int32_t type = p->pChasedCar->pRideInfo->Type;
    int32_t lang;

    if (cartypeinfo_get(type)->UsageType == CAR_USAGE_TYPE_COP)
        return 0x10000000;
    // Retail's jump table at 0x002bd3b0, by type - 5.
    switch (type) {
    case 5: case 6: case 13: case 14: case 43: case 44:
        lang = gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;
        if (lang == 1 || lang == 2)
            return PURSUIT_NO_DESCRIPTION;
        break;
    case 15: case 16: case 22:
        return PURSUIT_NO_DESCRIPTION;
    default:
        break;
    }
    return speech_convert_car_type(type);
}

int32_t tpursuit_can_supervisor_initiate(tPursuit *p)
{
    if (tpursuit_get_exact_description(p) == PURSUIT_NO_DESCRIPTION)
        return 0;
    return (uint32_t)(p->PursuitState - EPS_LEVEL2) < 2u;
}

void tpursuit_raise_backup_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();

    if (p->pChasedCar->pPlayer == NULL)
        return;
    if (p->CurrentLandmark != 0) {
        uint32_t speaker = tpursuit_get_cop_speaker(p);

        speechmgr_raise_backup_request_location(mgr, speaker,
                                                p->CurrentLandmark);
    } else {
        speechmgr_raise_backup_request(mgr, tpursuit_get_cop_speaker(p));
    }
}

void tpursuit_declare_pursuit_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    int32_t exact;
    uint32_t r;
    uint32_t speaker;
    int32_t colour;

    if (!tpursuit_is_player_involved(p))
        return;
    exact = tpursuit_get_exact_description(p);
    if (exact == PURSUIT_NO_DESCRIPTION) {
        speaker = tpursuit_get_cop_speaker(p);
        colour = tpursuit_get_chased_car_colour(p);
        speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);
        return;
    }
    r = random_below(40);
    if (r == 0) {
        speaker = tpursuit_get_cop_speaker(p);
        colour = tpursuit_get_chased_car_colour(p);
        speechmgr_raise_begin_pursuit_id_repeated(mgr, speaker, 0, exact,
                                                  colour);
    } else if (r < 17) {
        speaker = tpursuit_get_cop_speaker(p);
        colour = tpursuit_get_chased_car_colour(p);
        speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,
                                                  colour);
    } else if (r < 26) {
        speaker = tpursuit_get_cop_speaker(p);
        colour = tpursuit_get_chased_car_colour(p);
        speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);
    } else if (r < 36) {
        speechmgr_raise_cop_pursuit_avoidance(mgr,
                                              tpursuit_get_cop_speaker(p));
    } else {
        speechmgr_raise_begin_pursuit_no_id(mgr, tpursuit_get_cop_speaker(p));
    }
}

void tpursuit_begin_pursuit_collision_speech(tPursuit *p, struct Car *hit)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    uint32_t speaker;

    if (p->CurrentLandmark != 0) {
        speechmgr_raise_begin_pursuit_general(mgr,
                                              tpursuit_get_cop_speaker(p));
        return;
    }
    if (hit->MyDriver->TheDriverType == DRIVER_TYPE_COP) {
        speaker = tpursuit_get_cop_speaker(p);
        speechmgr_raise_begin_pursuit_cop_hit_run(mgr, speaker,
                                                  p->CurrentLandmark);
        tpursuit_switch_state(p, EPS_LEVEL2);
        return;
    }
    speaker = tpursuit_get_cop_speaker(p);
    speechmgr_raise_begin_pursuit_hit_run_traffic(mgr, speaker,
                                                  p->CurrentLandmark);
    if (p->PursuitState == EPS_LEVEL0)
        tpursuit_switch_state(p, EPS_LEVEL1);
}

void tpursuit_start_pursuit_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    int32_t exact;
    struct Car *hit;
    uint32_t speaker;
    int32_t colour;

    if (TheRaceParameters.BeACop != 0)
        speechmgr_flush_queue(mgr);
    exact = tpursuit_get_exact_description(p);
    if (!tpursuit_is_player_involved(p)) {
        if (in_demo())
            return;
        if (exact == PURSUIT_NO_DESCRIPTION) {
            speaker = tpursuit_get_cop_speaker(p);
            colour = tpursuit_get_chased_car_colour(p);
            speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);
        } else {
            speaker = copmanager_get_current_cop_speaker(pCopManager);
            colour = tpursuit_get_chased_car_colour(p);
            speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,
                                                      colour);
        }
        copmanager_next_cop_speaker(pCopManager);
        return;
    }
    if (TheRaceParameters.BeACop != 0) {
        speaker = tpursuit_get_cop_speaker(p);
        colour = tpursuit_get_chased_car_colour(p);
        if (exact == PURSUIT_NO_DESCRIPTION)
            speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);
        else
            speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,
                                                      colour);
        return;
    }
    hit = car_caused_recent_collision(p->pChasedCar);
    if (hit != NULL) {
        tpursuit_begin_pursuit_collision_speech(p, hit);
        p->PursuitSubState = 1;
        p->bAlreadyBeenHit = 1;
        return;
    }
    if (copmanager_get_num_tickets(pCopManager, p->pChasedCar) > 0) {
        tpursuit_switch_state(p, EPS_LEVEL1);
        if (random_below(10) < 8u && exact != PURSUIT_NO_DESCRIPTION) {
            speaker = tpursuit_get_cop_speaker(p);
            colour = tpursuit_get_chased_car_colour(p);
            speechmgr_raise_begin_pursuit_again(mgr, speaker, exact, colour);
            return;
        }
    }
    if (100.0f < tpursuit_get_speed_mph_or_kph(p)
        && random_below(10) < 7u) {
        speaker = tpursuit_get_cop_speaker(p);
        speechmgr_raise_begin_pursuit_speed(mgr, speaker,
                                            tpursuit_get_speed_mph_or_kph(p));
        return;
    }
    if (random_below(2) == 0)
        speechmgr_raise_begin_pursuit_erratic(mgr,
                                              tpursuit_get_cop_speaker(p));
    else
        speechmgr_raise_begin_pursuit_general(mgr,
                                              tpursuit_get_cop_speaker(p));
}

void tpursuit_join_pursuit_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    uint32_t speaker;
    uint32_t target;
    int32_t exact;
    int32_t colour;

    if (p->pChasedCar->pPlayer == NULL)
        return;
    if (p->PrimaryCopSpeaker == COP_SPEAKER_NONE) {
        speaker = copmanager_reserve_cop_speaker(pCopManager);
        p->PrimaryCopSpeaker = speaker;
        if (p->CurrentLandmark != 0) {
            speechmgr_raise_suspect_found(mgr, speaker, supervisor_on(),
                                          p->CurrentLandmark);
            return;
        }
        exact = tpursuit_get_exact_description(p);
        if (exact != PURSUIT_NO_DESCRIPTION) {
            speaker = tpursuit_get_cop_speaker(p);
            colour = tpursuit_get_chased_car_colour(p);
            speechmgr_raise_begin_pursuit_again(mgr, speaker, exact, colour);
        } else {
            speechmgr_raise_begin_pursuit_general(mgr,
                                                  tpursuit_get_cop_speaker(p));
        }
        return;
    }
    if (p->bAlreadyJoined != 0)
        return;
    if (p->PursuitState <= EPS_LEVEL0)
        return;
    p->bAlreadyJoined = 1;
    if (p->SecondaryCopSpeaker == COP_SPEAKER_NONE
        && TheRaceParameters.NumPlayerCars == 1) {
        speaker = copmanager_reserve_cop_speaker(pCopManager);
        p->SecondaryCopSpeaker = speaker;
    } else {
        speaker = copmanager_get_current_cop_speaker(pCopManager);
        copmanager_next_cop_speaker(pCopManager);
    }
    target = tpursuit_get_cop_speaker(p);
    speechmgr_raise_backup_confirm(mgr, speaker, target);
}

void tpursuit_roadblock_failed_speech(tPursuit *p, int32_t through)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    const tRoadBlock *rb;
    int32_t sup;
    uint32_t speaker;

    if (p->BehaviourFlags & 0x10u) {
        if (p->ChopperState == ECS_CHOPPER_ATTACKING
            && random_below(3) == 0) {
            // Retail hands the supervisor's bool as the speaker, and
            // whether the speaker is not 0 as the bool.
            sup = supervisor_on();
            speaker = tpursuit_get_cop_speaker(p);
            speechmgr_raise_rotor_spike_failed(mgr, (uint32_t)sup,
                                               speaker != 0);
        } else {
            sup = supervisor_on();
            rb = p->pRoadBlock;
            speaker = tpursuit_get_cop_speaker(p);
            speechmgr_raise_spike_strip_failure(mgr, rb->CopSpeaker, sup,
                                                speaker);
        }
    } else if (through != 0) {
        sup = supervisor_on();
        rb = p->pRoadBlock;
        speaker = tpursuit_get_cop_speaker(p);
        speechmgr_raise_road_block_failure_through(mgr, rb->CopSpeaker, sup,
                                                   speaker);
    } else {
        sup = supervisor_on();
        rb = p->pRoadBlock;
        speaker = tpursuit_get_cop_speaker(p);
        speechmgr_raise_road_block_failure_avoid(mgr, rb->CopSpeaker, sup,
                                                 speaker);
    }
    if (TheRaceParameters.BeACop == 0)
        speechmgr_raise_request_another_roadblock(mgr,
                                                  p->pRoadBlock->CopSpeaker,
                                                  supervisor_on());
}

void tpursuit_road_block_set_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    const tRoadBlock *rb = p->pRoadBlock;
    const Landmark *lm;
    int32_t location = 0;
    uint32_t r;

    lm = copmgr_find_landmark(&rb->v2Position);
    if (lm != NULL)
        location = lm->LandmarkType;
    r = random_below(20);
    if (p->BehaviourFlags & 0x10u) {
        if (r < 3u)
            speechmgr_raise_spike_strip_set(mgr, rb->CopSpeaker, location,
                                            supervisor_on());
        else if (rb->nSpikeSide == 2)
            speechmgr_raise_spike_strip_set_right(mgr, rb->CopSpeaker,
                                                  location, supervisor_on());
        else
            speechmgr_raise_spike_strip_set_left(mgr, rb->CopSpeaker,
                                                 location, supervisor_on());
    } else if (r < 3u) {
        speechmgr_raise_road_block_setting(mgr, rb->CopSpeaker,
                                           supervisor_on());
    } else {
        speechmgr_raise_road_block_set(mgr, rb->CopSpeaker, supervisor_on(),
                                       location);
    }
}

void tpursuit_cop_back_off_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    uint32_t speaker;

    if (p->nNumCops == 0
        || (supervisor_on() && random_below(4) != 0)) {
        speechmgr_raise_super_back_off(mgr);
        return;
    }
    speaker = tpursuit_get_cop_speaker(p);
    speechmgr_raise_cop_back_off(mgr, speaker, supervisor_on());
}

void tpursuit_ai_ticket_speech(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    uint32_t speaker;
    int32_t exact;

    if (in_demo())
        return;
    if (TheRaceParameters.BeACop != 0) {
        speaker = pCopManager->BeACopId;
    } else {
        speaker = copmanager_get_current_cop_speaker(pCopManager);
        copmanager_next_cop_speaker(pCopManager);
    }
    exact = tpursuit_get_exact_description(p);
    if (random_below(3) == 0 || exact == PURSUIT_NO_DESCRIPTION)
        speechmgr_raise_radio_arrest(mgr, speaker);
    else
        speechmgr_raise_car_stopped(mgr, speaker, exact);
}

void tpursuit_super_initiates(tPursuit *p)
{
    SpeechMgr *mgr = speechmgr_get_instance();
    uint32_t speaker = tpursuit_get_cop_speaker(p);
    float speed = tpursuit_get_speed_mph_or_kph(p);
    int32_t location = p->CurrentLandmark;
    int32_t exact = tpursuit_get_exact_description(p);
    int32_t colour = tpursuit_get_chased_car_colour(p);

    speechmgr_raise_super_initiate(mgr, speaker, speed, location, exact,
                                   colour);
}

void tpursuit_change_chase_target(tPursuit *p, struct Car *car)
{
    SpeechMgr *mgr;
    uint32_t speaker;
    int32_t exact;
    int32_t colour;

    p->pChasedCar = car;
    if (p->pChopper != NULL) {
        if (gChopperFollowThisCarFn == NULL) {
            fprintf(stderr, "pursuitspeech: the chopper (12k) is not "
                    "ported\n");
            abort();
        }
        gChopperFollowThisCarFn(p->pChopper, NULL);
    }
    speaker = TheRaceParameters.BeACop != 0 ? pCopManager->BeACopId
                                            : tpursuit_get_cop_speaker(p);
    exact = tpursuit_get_exact_description(p);
    colour = tpursuit_get_chased_car_colour(p);
    mgr = speechmgr_get_instance();
    if (exact == PURSUIT_NO_DESCRIPTION)
        speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);
    else
        speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,
                                                  colour);
}
