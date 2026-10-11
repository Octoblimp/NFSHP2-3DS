// raceovermsg -- see raceovermsg.h. Slice RE-2c.

#include "raceovermsg.h"

#include <stddef.h>

#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "flailerwrap.h"
#include "fred.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "racefinish.h"
#include "racerun.h"
#include "racesplit.h"

const char *(*gRaceOverTranslateFn)(int32_t id);
void (*gMaybeDoKnockoutRaceOverSpeechFn)(struct Player *p, int32_t advances);

// The message, sp+0 to sp+127 of retail's frame. bSPrintf has no bound.
#define MESSAGE_BYTES 128

// FormatTimeForRaceOverOverlay's text of the time (sp+0 of its frame).
#define TIME_BYTES 32

// PrintToString's rounding, a hundredth (gp-30248).
#define TIME_ROUNDING 0.01f

// The overlay's strings.
#define MSG_FINISHED          59010  // You finished in %s place!
#define MSG_ARRESTED          59011  // You were arrested!
#define MSG_ARRESTED_LAP      59012  // ...@You recorded a lap time of %s
#define MSG_ARRESTED_NO_LAP   59013  // ...@You didn't record a lap time.
#define MSG_ARRESTED_NO_END   59014  // ...@You didn't get to the finish.
#define MSG_LAP_TIME          59015  // You recorded a lap time of %s
#define MSG_TIME              59016  // You recorded a time of %s
#define MSG_ADVANCE           59017  // ...@You advance to the next race!
#define MSG_KNOCKED_OUT       59018  // ...@You were knocked out!
#define MSG_KNOCKED_OUT_LAP   59019  // ...@You finish in %s place!
#define MSG_ARRESTED_ALL      59020  // You arrested all of the racers!
#define MSG_QUOTA             59022  // You failed to fill@your ticket quota!
#define MSG_OUT_OF_TIME       59023  // Out of time!
#define MSG_P1_WIN            59024  // You win!
#define MSG_P1_LOSE           59025  // You lose!
#define MSG_P2_WIN            59026  // You win!
#define MSG_P2_LOSE           59027  // You lose!

// eEVENT_POINT2POINT, TheRaceEvent's type (+106).
#define RACE_EVENT_POINT2POINT 5

// A knockout of this many cars or more goes on to another race.
#define KNOCKOUT_ADVANCE_CARS 3

// The places' words, 0x002fc028: "0th", then "1st" (61009, not the 321002
// of the same text) to "8th".
#define NUM_PLACES 9
static const int32_t kPlaceIds[NUM_PLACES] = {
    321001, 61009, 321003, 321004, 321005, 321006, 321007, 321008, 321009,
};

static const char *translate(int32_t id)
{
    const char *s = gRaceOverTranslateFn != NULL ? gRaceOverTranslateFn(id)
                                                 : NULL;

    return s != NULL ? s : "";
}

static int32_t language(void)
{
    return gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;
}

void race_over_format_finish_position(char *buf, int32_t place, int32_t id)
{
    char fmt[MESSAGE_BYTES];
    const char *word = "";

    // The seam's answer need not outlast its next call (main.c's is one
    // buffer), so the format is copied out before the place's word is
    // asked for.
    b_snprintf(fmt, sizeof fmt, "%s", translate(id));
    if (place >= 0 && place < NUM_PLACES)
        word = translate(kPlaceIds[place]);
    b_snprintf(buf, MESSAGE_BYTES, fmt, word);
}

void race_over_format_time(char *buf, const Timer *t, int32_t id)
{
    char time[TIME_BYTES];

    timer_print_to_string_rounded(t, time, TIME_ROUNDING, 0, language());
    b_snprintf(buf, MESSAGE_BYTES, translate(id), time);
}

static void knockout_speech(struct Player *p, int32_t advances)
{
    if (gMaybeDoKnockoutRaceOverSpeechFn != NULL)
        gMaybeDoKnockoutRaceOverSpeechFn(p, advances);
}

// Whether the other player's car lost You're The Cop. Retail reads through
// PlayersByNumber unchecked; the port takes a missing one as not lost.
static int other_lost(int32_t number)
{
    const struct Player *o = PlayerPlayersByNumber[number];

    return o != NULL && o->MyCar != NULL && o->MyCar->pRacingCar != NULL
           && o->MyCar->pRacingCar->FinishReason
                  == RACING_CAR_BE_THE_COP_LOST;
}

// You're The Cop's message, or 0 for none.
static int32_t be_a_cop_message(const struct RacingCar *rc, int32_t reason)
{
    const struct Player *pl = racingcar_get_player(rc);

    if (TheRaceParameters.NumPlayerCars == 1)
        return reason == RACING_CAR_BE_THE_COP_WON ? MSG_ARRESTED_ALL
                                                   : MSG_QUOTA;
    if (TheRaceParameters.NumPlayerCars != 2 || pl == NULL)
        return 0;
    if (pl->PlayerNumber == 0) {
        if (reason == RACING_CAR_BE_THE_COP_WON)
            return MSG_P1_WIN;
        if (reason == RACING_CAR_BE_THE_COP_LOST)
            return other_lost(1) ? MSG_OUT_OF_TIME : MSG_P1_LOSE;
        return 0;
    }
    if (pl->PlayerNumber == 1) {
        if (reason == RACING_CAR_BE_THE_COP_WON)
            return MSG_P2_WIN;
        if (reason == RACING_CAR_BE_THE_COP_LOST)
            return other_lost(0) ? MSG_OUT_OF_TIME : MSG_P2_LOSE;
        if (reason == RACING_CAR_NORMAL_COMPLETION)
            return MSG_P2_WIN;
    }
    return 0;
}

void player_fill_in_race_over_messages(struct Player *p)
{
    struct RacingCar *rc = p->MyCar->pRacingCar;
    int32_t place = rc->FinishingOrder;
    int32_t reason = rc->FinishReason;
    Timer best = *racingcar_get_last_best_lap_time(rc);
    Timer race = rc->RaceTime;
    char buf[MESSAGE_BYTES];
    int32_t id = 0;

    buf[0] = 0;
    switch (TheRaceParameters.RaceType) {
    case RACE_TYPE_TIME_TRIAL:
        if (reason == RACING_CAR_ARRESTED) {
            if (timer_is_valid(&best))
                race_over_format_time(buf, &best, MSG_ARRESTED_LAP);
            else
                id = MSG_ARRESTED_NO_LAP;
        } else if (reason == RACING_CAR_NORMAL_COMPLETION) {
            race_over_format_time(buf, &best, MSG_LAP_TIME);
        }
        break;

    case RACE_TYPE_RACE_KNOCKOUT:
        if (reason == RACING_CAR_ARRESTED) {
            id = MSG_ARRESTED;
        } else if (reason == RACING_CAR_KNOCKED_OUT
                   || place == pCurrentRace->NumRacingCars) {
            race_over_format_finish_position(buf, place, MSG_KNOCKED_OUT);
            knockout_speech(p, 0);
        } else {
            race_over_format_finish_position(
                buf, place,
                pCurrentRace->NumRacingCars >= KNOCKOUT_ADVANCE_CARS
                    ? MSG_ADVANCE : MSG_FINISHED);
            knockout_speech(p, 1);
        }
        break;

    case RACE_TYPE_LAP_KNOCKOUT:
        if (reason == RACING_CAR_ARRESTED) {
            id = MSG_ARRESTED;
        } else if (reason == RACING_CAR_KNOCKED_OUT) {
            race_over_format_finish_position(buf, place, MSG_KNOCKED_OUT_LAP);
            knockout_speech(p, 0);
        } else {
            race_over_format_finish_position(buf, place, MSG_FINISHED);
        }
        break;

    case RACE_TYPE_SINGLE_RACE:
    case RACE_TYPE_TOURNAMENT:
        if (TheRaceParameters.BeACop != 0) {
            id = be_a_cop_message(rc, reason);
        } else if (fred_use_the_race_event(&Fred)
                   && TheRaceEvent.nType == RACE_EVENT_POINT2POINT) {
            if (reason == RACING_CAR_ARRESTED)
                id = MSG_ARRESTED_NO_END;
            else if (reason == RACING_CAR_NORMAL_COMPLETION)
                race_over_format_time(buf, &race, MSG_TIME);
        } else {
            // "You were arrested!" has no %s, but goes through the place's
            // format all the same.
            race_over_format_finish_position(
                buf, place,
                reason == RACING_CAR_ARRESTED ? MSG_ARRESTED : MSG_FINISHED);
        }
        break;

    default:
        break;
    }
    // Retail prints these with the string as the format and nothing to put
    // in; none has a '%' in any language, so the port copies it.
    if (id != 0)
        b_snprintf(buf, sizeof buf, "%s", translate(id));
    flailer_render_text_into_group(p->HudScreenHash, RACE_OVER_MESSAGE_GROUP,
                                   buf);
}
