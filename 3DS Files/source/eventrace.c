// eventrace -- the races an event sets. See eventrace.h; the decode is
// docs/formats/event-race.md.

#include "eventrace.h"

#include <string.h>

#include "bprintf.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "fred.h"
#include "startrace.h"
#include "timer.h"
#include "track.h"

const char *(*gEventRaceTranslateFn)(int32_t id);
const char *(*gEventRaceTranslateStringFn)(const char *s);

const EventDescriptionToken gEventDescriptionTokens[EVENT_TOKEN_COUNT] = {
    { EVENT_TOKEN_TARGET_TIME, "$TARGET_TIME" },
    { EVENT_TOKEN_NUM_LAPS, "$NUM_LAPS" },
    { EVENT_TOKEN_NUM_OPPONENTS, "$NUM_OPPONENTS" },
    { EVENT_TOKEN_NUM_RACES, "$NUM_RACES" },
    { EVENT_TOKEN_EVENTS_UNLOCKED, "$EVENTS_UNLOCKED" },
    { EVENT_TOKEN_COMPLETION_TIME, "$COMPLETION_TIME" },
    { EVENT_TOKEN_EVENT_UNLOCKED, "$EVENT_UNLOCKED" },
    { EVENT_TOKEN_TRACK_NAME, "$TRACK_NAME" },
};

// What a NULL table or state reads as: the bottom of memory, zeros in
// retail.
static const uint8_t kZeros[16];

// ---------------------------------------------------------- the helpers

static const char *translate(int32_t id)
{
    const char *s = gEventRaceTranslateFn != NULL ? gEventRaceTranslateFn(id)
                                                  : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static const char *translate_string(const char *s)
{
    const char *t = gEventRaceTranslateStringFn != NULL
                        ? gEventRaceTranslateStringFn(s) : NULL;

    return t != NULL ? t : s;
}

static uint32_t track_word(const uint8_t *b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16
           | (uint32_t)b[3] << 24;
}

// Entry `idx` of a tree's table of `size`-byte records; zeros for a NULL
// table.
static const void *entry(const void *table, int32_t idx, size_t size)
{
    if (table == NULL)
        return kZeros;
    return (const uint8_t *)table + (intptr_t)idx * (intptr_t)size;
}

// The reward's name into sRewardName: bStrNCpy's 32 (bStrCpy's for the
// two fixed strings), held to 31 and the NUL. The bytes after the NUL are
// left as they were.
static void copy_name(char *dst, const char *s)
{
    size_t n = strlen(s);

    if (n > 31)
        n = 31;
    memcpy(dst, s, n);
    dst[n] = 0;
}

// ---------------------------------------------------------- EventTrack

void event_track_set_race(const EventTrack *t, RaceParameters *rp)
{
    uint32_t w = track_word(t->b);
    const TrackInfo *ti;

    rp->TrackNumber = t->b[0];
    rp->NumLapsInRace = (int32_t)(w >> 14 & 0xf);
    rp->TrackWeather = (int32_t)(w >> 10 & 3);
    rp->TrackTimeOfDay = (int32_t)(w >> 12 & 3);
    rp->TrackDirection = (eTrackDirection)(w >> 9 & 1);
    rp->TrafficDensity = (float)(int32_t)(w >> 18 & 0x7f) * 0.01f;
    rp->TrafficOncoming = (float)(int32_t)(w >> 25) * 0.01f;
    ti = track_get_info(t->b[0]);
    if (ti != NULL)
        rp->Point2Point = ti->Point2Point;
}

void event_track_set_from_race(EventTrack *t, const RaceParameters *rp)
{
    uint32_t w;

    t->b[0] = (uint8_t)rp->TrackNumber;
    w = track_word(t->b);
    w = (w & 0xfffc3fffu) | (uint32_t)(rp->NumLapsInRace & 0xf) << 14;
    w = (w & 0xfffff3ffu) | (uint32_t)(rp->TrackWeather & 3) << 10;
    w = (w & 0xffffcfffu) | (uint32_t)(rp->TrackTimeOfDay & 3) << 12;
    w = (w & 0xfffffdffu) | (uint32_t)(rp->TrackDirection & 1) << 9;
    w = (w & 0xfe03ffffu)
        | ((uint32_t)ee_trunc_w(ee_mul(rp->TrafficDensity, 100.0f)) & 0x7f)
              << 18;
    w = (w & 0x01ffffffu)
        | (uint32_t)ee_trunc_w(ee_mul(rp->TrafficOncoming, 100.0f)) << 25;
    t->b[0] = (uint8_t)w;
    t->b[1] = (uint8_t)(w >> 8);
    t->b[2] = (uint8_t)(w >> 16);
    t->b[3] = (uint8_t)(w >> 24);
}

// ---------------------------------------------------------- EventTree

void event_tree_set_race(EventTree *tree, RaceParameters *rp, EventInfo *e)
{
    RaceEvent *ev = &TheRaceEvent;
    EventTree *et = event_info_tree(e);
    uint8_t *state = event_info_state(e);
    const EventReward *r;
    int32_t size, i;

    tree->pCurrentEvent = e;
    Fred.nCurrentEvent = e->nNumber;
    memcpy(ev->sName, e->sName, 32);
    size = event_info_get_state_size(e);
    memcpy(ev->aOldState, state != NULL ? state : kZeros, (size_t)size);
    ev->pTree = et;
    ev->pState = state;
    ev->nNumber = e->nNumber;
    ev->nType = e->nType;
    ev->nClass = e->nClass;
    ev->nCars = e->nCars;
    ev->nTracks = e->nTracks;
    ev->nRewards = e->nRewards;
    ev->nInitialPlayers = 1;
    ev->nOpponents = e->nOpponents;
    memcpy(&ev->Objective,
           entry(et != NULL ? et->pGoals : NULL, e->nObjective, 8), 8);

    // Retail copies every entry under the counts, past the arrays when a
    // count runs over; the port stops at each array's end.
    for (i = 0; i < e->nCars && i < 20; i++)
        memcpy(ev->aCars[i],
               entry(et != NULL ? et->pCars : NULL, e->aCars[i], 4), 4);
    for (i = 0; i < e->nTracks && i < 8; i++)
        memcpy(ev->aTracks[i].b,
               entry(et != NULL ? et->pTracks : NULL, e->aTracks[i], 4), 4);
    for (i = 0; i < e->nRewards && i < 8; i++)
        memcpy(&ev->aRewards[i],
               entry(et != NULL ? et->pRewards : NULL, e->aRewards[i], 8),
               8);
    for (i = 0; i < e->nOpponents && i < 7; i++)
        memcpy(ev->aOpponents[i],
               entry(et != NULL ? et->pOpponents : NULL, e->aOpponents[i],
                     4), 4);

    // The first reward's name: a car's, a track's, or neither.
    r = &ev->aRewards[0];
    if (e->nRewards <= 0) {
        copy_name(ev->sRewardName, translate_string("No reward"));
    } else if (r->nType == REWARD_CAR) {
        const CarTypeInfo *ct = cartypeinfo_get(r->nValue1);

        // CarTypeInfo::GetShortName (0x00187eb8), the full name's id.
        copy_name(ev->sRewardName,
                  translate_string(translate(ct->pCarSpecs->FullName)));
    } else if (r->nType == REWARD_TRACK) {
        const TrackInfo *ti = track_get_info(r->nValue1);

        // GetTheRightTrackLanguageID(int, dir), 0x001dc5a8; a NULL
        // TrackInfo reads zeros in retail.
        copy_name(ev->sRewardName,
                  translate(ti != NULL
                            ? get_the_right_track_language_id(ti, r->nValue2)
                            : 0));
    } else {
        copy_name(ev->sRewardName, translate_string("Unhandled type"));
    }

    format_event_description(tree, e, translate(e->mDescriptionString),
                             rp->sObjective, 512);
    rp->HasObjective = 1;
    raceevent_reset_results(ev);
    rp->nNumTicketsBeforeArrest = 2;
    rp->TimeTrialTime.PackedTime = 0;
    rp->BeACop = 0;

    switch (ev->nType) {
    case EVENT_TIME_TRIAL:
        rp->RaceType = 2;
        rp->TimeTrialTime.PackedTime = (int32_t)ev->Objective.nData;
        break;
    case EVENT_LAP_KNOCKOUT:
        rp->RaceType = 3;
        break;
    case EVENT_RACE_KNOCKOUT:
        rp->RaceType = 4;
        // A NULL state: retail's seed is written to, and read from, the
        // bottom of memory. The port leaves New780 as it was.
        if (state != NULL) {
            if (ko_state_get_race_index(state) == 0)
                ko_state_new_seed(state);
            rp->New780 = (int32_t)ko_state_get_seed(state);
        }
        break;
    case EVENT_TOURNAMENT:
        rp->RaceType = 5;
        if (state != NULL) {
            if (tournament_state_get_race_index(state, e->nOpponents) == 0)
                tournament_state_new_seed(state);
            rp->New780 = (int32_t)tournament_state_get_seed(state);
        }
        break;
    case EVENT_POINT2POINT:
        rp->Point2Point = 1;
        rp->RaceType = 1;
        rp->TimeTrialTime.PackedTime = (int32_t)ev->Objective.nData;
        break;
    case EVENT_BE_A_COP:
        rp->nNumTicketsBeforeArrest = 0;
        rp->BeACop = 1;
        rp->BeACopResetTimerAfterArrest = 0;
        rp->RaceType = 1;
        rp->TimeTrialTime.PackedTime = (int32_t)ev->Objective.nData;
        break;
    default:
        rp->RaceType = 1;
        break;
    }

    rp->NumPlayerCars = 1;
    rp->nMaxCops = tree->nType == EVENT_TREE_HOT_PURSUIT ? 6 : 0;
    rp->NumAICars = e->nOpponents;
    rp->OpponentSelect = e->nOpponentSelect;
    rp->CopStrength = e->eCopStrength;
    rp->bTickets = e->bTickets;
    rp->bRoadBlocks = e->bRoadBlocks;
    rp->bSpikeStrips = e->bSpikeStrips;
    rp->bHelicopter = e->bHelicopter;
    rp->New624 = e->New56;
    rp->nNumBeACopRoadBlocks = e->nNumBeACopRoadBlocks;
    rp->nNumBeACopChoppers = e->nNumBeACopChoppers;
    rp->TrainingLinesEnabled = 0;
    rp->DamageEnabled = e->New184 != 0;
    rp->PlayerStartPosition[0] = (int8_t)(uint8_t)(e->nOpponents + 1);
    rp->BoostScale[0] = e->fOpponentBoostScale;
    rp->BoostScale[1] = e->fOpponentBoostScale;
}

// ---------------------------------------------------- the description

const EventDescriptionToken *get_event_description_token(const char *src)
{
    int32_t i;

    for (i = 0; i < EVENT_TOKEN_COUNT; i++) {
        const char *name = gEventDescriptionTokens[i].sName;

        if (strncmp(name, src, strlen(name)) == 0)
            return &gEventDescriptionTokens[i];
    }
    return NULL;
}

void format_event_description_token(const EventTree *tree,
                                    const EventInfo *e,
                                    const EventDescriptionToken *tok,
                                    char *out)
{
    switch (tok->nId) {
    case EVENT_TOKEN_TARGET_TIME: {
        const EventGoal *g = (const EventGoal *)entry(tree->pGoals,
                                                      e->nObjective, 8);

        if (g->nType == 2) {
            Timer t;
            char buf[32];
            const char *p = buf;

            t.PackedTime = (int32_t)g->nData;
            timer_print_to_string(&t, buf, 0,
                                  gCurrLanguageFn != NULL ? gCurrLanguageFn()
                                                          : 0);
            while (*p == ' ')
                p++;
            // bSPrintf with the time as its format.
            b_snprintf(out, EVENT_TOKEN_TEXT, p);
        } else {
            strcpy(out, "zz:zz");
        }
        break;
    }
    case EVENT_TOKEN_NUM_LAPS: {
        uint32_t w = track_word((const uint8_t *)entry(tree->pTracks,
                                                       e->aTracks[0], 4));

        b_snprintf(out, EVENT_TOKEN_TEXT, "%d", (int)(w >> 14 & 0xf));
        break;
    }
    case EVENT_TOKEN_NUM_OPPONENTS:
        b_snprintf(out, EVENT_TOKEN_TEXT, "%d", (int)e->nOpponents);
        break;
    case EVENT_TOKEN_NUM_RACES:
        b_snprintf(out, EVENT_TOKEN_TEXT, "%d",
                   (int)event_info_get_race_count(e));
        break;
    case EVENT_TOKEN_EVENTS_UNLOCKED:
        strcpy(out, "events x,y,z are Unlocked!");
        break;
    case EVENT_TOKEN_COMPLETION_TIME:
        strcpy(out, "ff:ggg");
        break;
    case EVENT_TOKEN_EVENT_UNLOCKED:
        strcpy(out, "event x is unlocked");
        break;
    case EVENT_TOKEN_TRACK_NAME:
        strcpy(out, "TRACK_NAME_HERE");
        break;
    default:
        break;
    }
}

// Retail copies while fewer than n characters are out and then writes the
// NUL after them, at dst[n] when the text fills the buffer. The port runs
// the same loop, tokens and all, but keeps n - 1 characters: its text is
// retail's cut one short of the end.
static void put(char *dst, int32_t n, int32_t pos, char c)
{
    if (pos < n - 1)
        dst[pos] = c;
}

void format_event_description(const EventTree *tree, const EventInfo *e,
                              const char *src, char *dst, int32_t n)
{
    int32_t pos = 0;

    if (n <= 0)
        return;
    if (*src != 0) {
        do {
            const EventDescriptionToken *tok =
                *src == '$' ? get_event_description_token(src) : NULL;

            if (tok != NULL) {
                char text[EVENT_TOKEN_TEXT];
                const char *p = text;

                src += strlen(tok->sName);
                text[0] = 0;
                format_event_description_token(tree, e, tok, text);
                while (*p != 0 && pos < n)
                    put(dst, n, pos++, *p++);
            } else {
                put(dst, n, pos++, *src++);
            }
        } while (*src != 0 && pos < n);
    }
    dst[pos < n ? pos : n - 1] = 0;
}
