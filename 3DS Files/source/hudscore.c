// hudscore -- see hudscore.h.

#include "hudscore.h"

#include <stddef.h>

#include "bprintf.h"
#include "car.h"
#include "carinit.h"
#include "collision.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "flailer.h"
#include "hudanim.h"
#include "hudrender.h"
#include "player.h"
#include "playerinit.h"
#include "race.h"
#include "raceparams.h"
#include "rcstates.h"
#include "realtime.h"
#include "sundraw.h"
#include "vtable.h"

#define TICK_SECONDS 0.00025f           // gp-30328 and gp-30324

// The literals. StartScore's place and scale are gp-30364 and gp-30360 in
// one, gp-30356 and gp-30352 in the other, the same two numbers.
#define SCORE_X          530.0f
#define SCORE_Y          236.0f
#define SCORE_SCALE        0.7f
#define SCORE_DX2         90.0f         // 42b40000
#define SCORE_DY2       -100.0f         // c2c80000
#define SCORE_TITLE_UP    20.0f         // 41a00000
#define TWO_PLAYER_Y0     40.0f         // 42200000
#define TWO_PLAYER_Y1    280.0f         // 438c0000

// UpdateScoring's: a knock counts when the other body's inverse mass is
// below 500 (43fa0000), the impulse's direction is within 0.8 of level
// with the car (gp-30340 and gp-30336) and the collision's impulses add up
// past 8.3333 (gp-30332, 41055532). Air time is scored at 250 a second
// (437a0000), in steps of 50.
#define KNOCK_MASS_INVERSE 500.0f
#define KNOCK_LEVEL          0.8f
#define KNOCK_IMPULSE        8.3333f
#define AIR_PER_SECOND     250.0f
#define AIR_STEP              50

// The animators' slots.
#define SLOT_SCORE 10
#define SLOT_TITLE 11

static HudAnimator *slot_animator(struct Player *p, int32_t slot)
{
    if (p->pHudAnimations[slot] == NULL)
        p->pHudAnimations[slot] = hudanim_new();
    return p->pHudAnimations[slot];
}

static const char *translate(int32_t id)
{
    const char *s = gHudTranslateFn != NULL ? gHudTranslateFn(id) : NULL;

    return s != NULL ? s : "";
}

// ------------------------------------------------------------ the sound

void play_score_sound(int32_t scoring)
{
    RCState state;
    struct bSample *smp;

    if (!SoundEnabled)
        return;
    // The port's test; retail reads the state through it.
    if (pRaceCoordinator == NULL)
        return;
    state = racecoordinator_get_current_state(pRaceCoordinator);
    if (state == RCSTATE_INSTANT_REPLAY || state == RCSTATE_POSTRACE
        || state == RCSTATE_AUTO_REPLAY
        || racecoordinator_is_replay_demo_mode(pRaceCoordinator))
        return;
    if (scoring != SCORING_BEAT_THE_COPS && scoring != SCORING_TOOK_1ST_PLACE
        && scoring != SCORING_TOP_SPEED && scoring != SCORING_QUOTA_FILLED)
        return;
    smp = gGetInGameSampleFn != NULL ? gGetInGameSampleFn("ScorePoints")
                                     : NULL;
    if (smp == NULL)
        return;
    if (gSampleIsPlayingFn != NULL && gSampleIsPlayingFn(smp))
        return;
    if (gSamplePlayFn != NULL)
        gSamplePlayFn(smp, 1.0f, 0.0f, 0.0f);
}

// ------------------------------------------------------- the animation

void player_start_score_animation(struct Player *p, const bVector2 *pos,
                                  const bVector2 *dpos,
                                  const bVector2 *dpos2,
                                  const bVector2 *scale,
                                  const bVector2 *dscale,
                                  const bVector4 *colour,
                                  const bVector4 *dcolour)
{
    // By value in retail: the halves change the copies.
    bVector2 at = *pos, d = *dpos, d2 = *dpos2;
    HudAnimator *a;

    if (PlayerNumPlayers >= 2) {
        if (p->PlayerNumber == 0) {
            at.y = at.y * 0.5f;
            d.y = d.y * 0.5f;
            d2.y = d2.y * 0.5f;
            at.y = at.y + TWO_PLAYER_Y0;
        }
        if (p->PlayerNumber == 1) {
            at.y = at.y * 0.5f;
            d.y = d.y * 0.5f;
            d2.y = d2.y * 0.5f;
            at.y = at.y + TWO_PLAYER_Y1;
        }
    }
    a = slot_animator(p, SLOT_SCORE);
    if (a->bActive)
        player_add_to_total_score(p, p->strPrevScore);
    hudanim_start_scored(a, (struct FlailerTextChunk *)(void *)
                            p->pFlailerEventScore,
                         &at, &d, &d2, scale, dscale, 0, 128.0f, colour,
                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,
                         1.0f, NULL, 0);
    a = slot_animator(p, SLOT_TITLE);
    b_snprintf(p->strPrevScore, sizeof p->strPrevScore, "%s",
               p->strEventScore);
    at.y = at.y - SCORE_TITLE_UP;
    hudanim_start_scored(a, (struct FlailerTextChunk *)(void *)
                            p->pFlailerEventTitle,
                         &at, &d, &d2, scale, dscale, 0, 128.0f, colour,
                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,
                         1.0f, NULL, 0);
    p->tScoreAnimation.PackedTime = (uint32_t)WorldTimer;
}

// StartScore's place, built on the stack in every one. The colours' fourth
// lanes are not written there; here they are 0.
static void start_default_animation(struct Player *p)
{
    bVector2 pos = { SCORE_X, SCORE_Y };
    bVector2 dpos = { 0.0f, 0.0f };
    bVector2 dpos2 = { SCORE_DX2, SCORE_DY2 };
    bVector2 scale = { SCORE_SCALE, SCORE_SCALE };
    bVector2 dscale = { 0.0f, 0.0f };
    bVector4 colour = { 128.0f, 64.0f, 0.0f, 0.0f };
    bVector4 dcolour = { 0.0f, 64.0f, 128.0f, 0.0f };

    player_start_score_animation(p, &pos, &dpos, &dpos2, &scale, &dscale,
                                 &colour, &dcolour);
}

// ----------------------------------------------------------- the scores

int32_t player_get_finish_bonus(struct Player *p, int32_t place)
{
    if (place == 1)
        return player_convert_score_string(
            p, ScoreInfoTable[SCORING_1ST_PLACE_BONUS].Score);
    if (place == 2)
        return player_convert_score_string(
            p, ScoreInfoTable[SCORING_2ND_PLACE_BONUS].Score);
    if (place == 3)
        return player_convert_score_string(
            p, ScoreInfoTable[SCORING_3RD_PLACE_BONUS].Score);
    return 0;
}

// Retail prints the score and the title as bSPrintf's format, unbounded.
// No score or title in any language holds a %, and the longest title,
// Italian's HIT COP CAR, is 31 characters, so "%s" bounded is the same.
void player_start_score(struct Player *p, int32_t scoring)
{
    const ScoreInfo *info = &ScoreInfoTable[scoring];

    play_score_sound(scoring);
    b_snprintf(p->strEventScore, sizeof p->strEventScore, "%s", info->Score);
    b_snprintf(p->strEventTitle, sizeof p->strEventTitle, "%s",
               translate(info->NameId));
    start_default_animation(p);
}

void player_start_score_value(struct Player *p, int32_t scoring,
                              int32_t value)
{
    (void)value;
    play_score_sound(scoring);
    b_snprintf(p->strEventTitle, sizeof p->strEventTitle, "%s",
               translate(ScoreInfoTable[scoring].NameId));
    start_default_animation(p);
}

// ------------------------------------------------------------- the frame

typedef float (*VtMassInverseFn)(void *self);

static float get_mass_inverse(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_MASS_INVERSE);

    return ((VtMassInverseFn)e->fn)(vt_this(b, e));
}

// `vmul.xyz ; vaddy.x ; vaddz.x`.
static float dot3(const bVector3 *a, const bVector4 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// baPlaceReached[pos - 1], which retail bounds neither way. A race's
// places are 1 to 8; another place reaches the Player's word that far
// along, as retail's does: 0 is bSegmentCollisionDetected, 9
// bShownMusicTitle, -1 LastCrossingTime and 14 fInitialPursuitY, all
// words. Below -1 lies lastCar, a pointer, and past 14 the score would be
// read from past ScoreInfoTable's end, so those places are skipped.
static int32_t *place_reached(struct Player *p, int32_t pos)
{
    if (pos < -1 || pos >= NUM_SCORE_INFOS - SCORING_START_BONUS)
        return NULL;
    return (int32_t *)(void *)((char *)p->baPlaceReached + 4 * (pos - 1));
}

// The lap's end: a clean lap, a lap led, or a clean segment.
static void score_lap(struct Player *p, const struct RacingCar *rc)
{
    int32_t timed = 0;

    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL
        && timer_is_valid(&TheRaceParameters.TimeTrialTime))
        timed = TheRaceParameters.BeACop == 0;
    if (timed || TheRaceParameters.Point2Point != 0) {
        if (!p->bSegmentCollisionDetected)
            player_start_score(p, SCORING_CLEAN_SEGMENT);
        p->bSegmentCollisionDetected = 0;
        return;
    }
    if (!p->bCollisionDetected) {
        player_start_score(p, SCORING_CLEAN_LAP);
        p->numCleanLaps = p->numCleanLaps + 1;
    } else if (rc->RacePosition == 1) {
        player_start_score(p, rc->NumLapsCompleted == 1
                                  ? SCORING_LED_FIRST_LAP
                                  : SCORING_LED_A_LAP);
    } else if (!p->bSegmentCollisionDetected && rc->NumLapsCompleted > 0) {
        player_start_score(p, SCORING_CLEAN_SEGMENT);
    }
    p->bSegmentCollisionDetected = 0;
    p->bCollisionDetected = 0;
}

// This frame's collision of the car's body, if it is a knock: the other
// body light enough, the car on the ground, the impulse near level and
// hard enough. A knock spoils the lap and the segment.
static void score_knock(struct Player *p, struct Car *car)
{
    Collision *c = collisionbody_get_collision(
        &car->pDynamicCollisionBody->Dynamic.Body, 0);
    struct Car *car1, *car2;
    int32_t which = -1;
    float m1, m2, other, d;

    if (c == NULL)
        return;
    collision_get_colliding_cars(c, &car1, &car2);
    if (car1 != NULL && car1->pPlayer == p)
        which = 0;
    if (car2 != NULL && car2->pPlayer == p)
        which = 1;
    if (which < 0) {
        p->bSmokeableHit = 0;
        return;
    }
    m1 = get_mass_inverse(c->pWitness->pBody1);
    m2 = get_mass_inverse(c->pWitness->pBody2);
    other = which == 0 ? m2 : m1;
    if (!(other < KNOCK_MASS_INVERSE))
        return;
    if (!(p->HangTime == 0.0f))
        return;
    // Row 2 of the body's matrix, its up.
    d = dot3(&c->ImpulseDirection, &car->State.BodyMatrix.v2);
    if (!(d < KNOCK_LEVEL) || !(-KNOCK_LEVEL < d) || d == 0.0f)
        return;
    if (!(KNOCK_IMPULSE < c->TotalImpulseMagnitude))
        return;
    p->bCollisionDetected = 1;
    p->bSegmentCollisionDetected = 1;
    p->New2540 = 0;
    if (collision_is_smokeable_involved(c)) {
        if (!p->bSmokeableHit)
            p->bSmokeableHit = 1;
    } else {
        p->bSmokeableHit = 0;
    }
}

// Air time: the clock at take-off, and on landing its length in score.
static void score_air(struct Player *p, struct Car *car)
{
    int32_t air;

    if (car->State.nWheelsTouchingGround == 0) {
        if (p->HangTime == 0.0f)
            p->HangTime = (float)WorldTimer * TICK_SECONDS;
        return;
    }
    if (p->HangTime == 0.0f) {
        p->HangTime = 0.0f;
        return;
    }
    air = ee_trunc_w(((float)WorldTimer * TICK_SECONDS - p->HangTime)
                     * AIR_PER_SECOND);
    air = air / AIR_STEP * AIR_STEP;
    if ((uint32_t)air - 100u < 100u) {
        b_snprintf(p->strEventScore, sizeof p->strEventScore, "+%d", air);
        player_start_score_value(p, SCORING_AIR, air);
    }
    if ((uint32_t)air - 200u < 150u) {
        b_snprintf(p->strEventScore, sizeof p->strEventScore, "+%d", air);
        player_start_score_value(p, SCORING_BIG_AIR, air);
    }
    if (air >= 350) {
        b_snprintf(p->strEventScore, sizeof p->strEventScore, "+%d", air);
        player_start_score_value(p, SCORING_HUGE_AIR, air);
    }
    p->HangTime = 0.0f;
}

void player_update_scoring(struct Player *p)
{
    struct Car *car = p->MyCar;
    struct RacingCar *rc = race_get_racing_car(pCurrentRace, car);

    if (car_is_blinking(car)) {
        p->HangTime = 0.0f;
        bResetGlare = 1;
        return;
    }
    if (rc != NULL && rc->FinishReason == 0 && rc->CrossedFinishLine != 0)
        score_lap(p, rc);
    if (p->bNewTopSpeed)
        player_start_score(p, SCORING_TOP_SPEED);
    score_knock(p, car);
    score_air(p, car);
    // A place taken, once a race each, but never as the cop.
    if (p->PositionFlag > 0) {
        int32_t pos = p->LastRacePosition;
        int32_t *reached = place_reached(p, pos);

        if (reached != NULL && !*reached && !TheRaceParameters.BeACop) {
            player_start_score(p, pos + SCORING_START_BONUS);
            *reached = 1;
        }
    }
    p->PositionFlag = 0;
}
