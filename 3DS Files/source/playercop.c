// playercop -- Be A Cop's player cop. See playercop.h.

#include "playercop.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "car.h"
#include "chopper.h"
#include "playerhud.h"
#include "playerinit.h"
#include "pursuit.h"
#include "pursuitspeech.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"
#include "world.h"

#define PICKS               2
#define PICK_HOLD           5.0f        // 40a00000
#define CHASE_RANGE         175.0f      // 432f0000
#define CHASE_NEAR          20.0f       // 41a00000, the z and the near range
#define CHASE_SCORE         185.0f      // 43390000
#define CHASE_AHEAD         10000       // IsCarInFront's BAM
#define CHOPPER_SPENT       4           // salvos before it is let go

// Car+2056 as retail stores it and reads it, a word: CopLights and the
// three bytes after.
static void set_cop_lights(Car *car, int8_t v)
{
    car->CopLights = v;
    memset(car->_hole2025, 0, sizeof car->_hole2025);
}

static int cop_lights_word(const Car *car)
{
    const uint8_t *p = (const uint8_t *)car + offsetof(Car, CopLights);

    return (p[0] | p[1] | p[2] | p[3]) != 0;
}

// Whether any of the cars before CopCarPos is pulled over. Retail reads
// CarPullovers[k].bActive for k up to CopCarPos, which no World takes past
// the eight.
static int any_pulled_over(void)
{
    int32_t n = pCurrentWorld->CopCarPos;
    int32_t k;

    for (k = 0; k < n && k < COPMANAGER_NUM_PULLOVERS; k++)
        if (pCopManager->CarPullovers[k].bActive != 0)
            return 1;
    return 0;
}

void tplayercop_think(tPlayerCop *c)
{
    Car      *car = c->Base.pMyCar;
    tPursuit *p;
    int       i;

    if (car->pPlayer != NULL && !player_is_nis_playing(car->pPlayer))
        for (i = 0; i < PICKS; i++) {
            c->fPrevSelectionTimer[i] -= WorldTimeElapsed;
            if (c->fPrevSelectionTimer[i] <= 0.0f) {
                c->fPrevSelectionTimer[i] = 0.0f;
                c->nPrevSelection[i] = -1;
            }
        }
    p = c->Base.pMyPursuit;
    if (p != NULL) {
        car->TheSirenMode = SIREN_MODE_01;
        set_cop_lights(car, 2);
    } else if (any_pulled_over()) {
        car->TheSirenMode = SIREN_MODE_NONE;
        set_cop_lights(car, 2);
    }
    if (p != NULL && p->pChopper != NULL
        && p->pChopper->TotalSalvos >= CHOPPER_SPENT)
        tpursuit_release_chopper(p);
}

void tplayercop_change_chase_target(tPlayerCop *c)
{
    Car      *car = c->Base.pMyCar;
    Car      *pick;
    tPursuit *p;

    if (car->pPlayer == NULL || player_is_nis_playing(car->pPlayer))
        return;
    pick = tplayercop_select_car_to_chase(c);
    p = c->Base.pMyPursuit;
    if (pick != NULL) {
        struct bSample *s;

        if (p == NULL) {
            (void)copmanager_request_pursuit(pCopManager, &c->Base, pick);
            return;
        }
        if (p->pChasedCar != pick) {
            tpursuit_change_chase_target(p, pick);
            return;
        }
        s = gGetInGameSampleFn != NULL
            ? gGetInGameSampleFn("BeACopRequestFailed") : NULL;
        if (s != NULL && gSamplePlayFn != NULL)
            gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);
        return;
    }
    if (p != NULL)
        return;
    car = c->Base.pMyCar;
    set_cop_lights(car, cop_lights_word(car) ? 0 : 1);
}

struct Car *tplayercop_select_car_to_chase(tPlayerCop *c)
{
    float   score[WORLD_MAX_CARS];
    int32_t n = pCurrentWorld->CopCarPos;
    int32_t was = c->nPrevSelection[0];
    int32_t before = c->nPrevSelection[1];
    int32_t best = -1;
    float   top = -1.0f;
    int32_t i;

    for (i = 0; i < n; i++) {
        Car  *o = pCurrentWorld->CarTable[i];
        Car  *mine;
        float dx, dy, d, dz;

        score[i] = -1.0f;
        if (o == c->Base.pMyCar || car_is_blinking(o)
            || o->pRacingCar->FinishReason != 0)
            continue;
        mine = c->Base.pMyCar;
        dx = mine->State.Position.x - o->State.Position.x;
        dy = mine->State.Position.y - o->State.Position.y;
        d = sqrtf(dx * dx + dy * dy);
        dz = fabsf(mine->State.Position.z - o->State.Position.z);
        if (dz < CHASE_NEAR && d < CHASE_RANGE
            && car_is_car_in_front(mine, o, CHASE_AHEAD))
            score[i] = CHASE_SCORE - d;
        else if (d < CHASE_NEAR)
            score[i] = CHASE_SCORE - d;
    }
    // Retail's picks are always below CopCarPos, or -1.
    if (was >= 0 && was < n && -1.0f < score[was])
        score[was] = 0.0f;
    if (before >= 0 && before < n && -1.0f < score[before])
        score[before] = PICK_HOLD;
    for (i = 0; i < n; i++)
        if (top < score[i]) {
            top = score[i];
            best = i;
        }
    if (best == -1)
        return NULL;
    c->nPrevSelection[0] = best;
    c->nPrevSelection[1] = was;
    c->fPrevSelectionTimer[1] = c->fPrevSelectionTimer[0];
    c->fPrevSelectionTimer[0] = PICK_HOLD;
    return pCurrentWorld->CarTable[best];
}

void copmanager_be_a_cop_toggle_siren_and_lights(tCopManager *m)
{
    tCop *c;

    if (pCurrentRace->RaceStage != RACE_STAGE_RACING)
        return;
    c = copmanager_get_player_cop(m);
    if (c != NULL)
        tplayercop_change_chase_target((tPlayerCop *)c);
}
