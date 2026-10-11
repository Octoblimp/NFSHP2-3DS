// endevent -- the career's end-game screens; endevent.h has the map.

#include "endevent.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "bprintf.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "eefpu.h"
#include "endresults.h"
#include "eventtree.h"
#include "flailer.h"
#include "fred.h"
#include "fredend.h"
#include "fredevent.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "raceevent.h"
#include "racerun.h"
#include "racespeech.h"
#include "startrace.h"
#include "track.h"
#include "world.h"

// Everything here is bMalloc'd in pool 16.
#define END_EVENT_POOL 16

// The once-only speech flags on the screens' list (endgame.h).
#define EVENTS_UNLOCKED_SPEECH_SAID(s) ((s)->Zeroed[2])
#define EVENT_REWARD_SPEECH_SAID(s)    ((s)->Zeroed[3])
#define TOURNEY_SPEECH_SAID(s)         ((s)->Zeroed[6])

// The GameTypes of the two event trees, by what their strings call them.
#define GAME_TYPE_CHAMPIONSHIP   8
#define GAME_TYPE_ULTIMATE_RACER 9

// RaceParameters' RaceType for a time trial.
#define RACE_TYPE_TIME_TRIAL 2

// A TimeTrialTime that is no time.
#define NO_TIME 0x7fffffffu

// eGoalType: an objective of a place, or of a time.
#define GOAL_PLACE 1
#define GOAL_TIME  2

// The events with a reward screen of their own: each tree's last before
// the Ultimate, its bonus event, and the Ultimate (EVENT_ULTIMATE).
#define EVENT_TREE_LAST  30
#define EVENT_TREE_BONUS 31

// TransientStats' FinishReason in You're The Cop (racefinish.h's).
#define BTC_REASON_COMPLETED 1
#define BTC_REASON_WON       4
#define BTC_REASON_LOST      5

// The Reward menu's blurbs, by how the event went.
#define LANG_LAP_FAILED        0xe09c0  // best lap, the time to beat
#define LANG_LAP_UNLOCKED      0xe09c1  // best lap, the reward
#define LANG_TOTAL_FAILED      0xe09c2  // total time, the time to beat
#define LANG_TOTAL_UNLOCKED    0xe09c3  // total time, the reward
#define LANG_COP_UNLOCKED      0xe09c4  // the reward
#define LANG_COP_FAILED        0xe09c5
#define LANG_LAP_PASSED        0xe09c6  // best lap
#define LANG_TOTAL_PASSED      0xe09c7  // total time
#define LANG_FIRST_UNLOCKED    0xe30d0  // the reward
#define LANG_SECOND_UNLOCKED   0xe30d1  // the reward
#define LANG_THIRD_UNLOCKED    0xe30d2  // the reward
#define LANG_PLACE_FAILED      0xe30d3  // the place, the place needed
#define LANG_PASSED_UNLOCKED   0xe30d4  // the reward
#define LANG_CHAMPION          0xe30d5  // the World Champion
#define LANG_ROAD_RACER        0xe30d6  // the Ultimate Road Racer
#define LANG_FIRST             0xe30da
#define LANG_SECOND            0xe30db
#define LANG_THIRD             0xe30dc
#define LANG_PASSED            0xe30dd
#define LANG_HP_CHAMPION       0xe32c4  // the Hot Pursuit Champion
#define LANG_BONUS_CHAMPIONSHIP 0xe32c5 // the F50 Endurance Challenge
#define LANG_BONUS_ULTIMATE    0xe32c6  // the 550 Endurance Challenge
// "track", after a track's name.
#define LANG_TRACK             0xe09bf

// You're The Cop 2P's blurbs, the cop's (the first player's) and the
// speeder's: the speeder busted, the speeder away, and the time run out
// on both.
#define LANG_BTC_COP_WON       0xecd1c
#define LANG_BTC_SPEEDER_LOST  0xecd1f
#define LANG_BTC_COP_LOST      0xecd1d
#define LANG_BTC_SPEEDER_WON   0xecd1e
#define LANG_BTC_COP_TIME_UP   0xecd25
#define LANG_BTC_SPEEDER_TIME_UP 0xecd26

// The places' names, "0th" to "8th", and the 0 after them (0x002b9178).
static const int32_t kPlaceNames[10] = {
    0xee48, 0xee49, 0xee4a, 0xee4b, 0xee4c, 0xee4d, 0xee4e, 0xee4f, 0xee50,
    0,
};

// Events Unlocked's blurbs for one, two and three events, by tree
// (0x002b8e60, 0x002b8e70).
static const int32_t kChampionshipUnlocked[4] = {
    0, 0xde2b0, 0xde2b4, 0xde2b1,
};
static const int32_t kUltimateRacerUnlocked[4] = {
    0, 0xde2b2, 0xde2b5, 0xde2b3,
};

// What retail reads through a NULL state or row: the bottom of memory,
// zeros in the image.
static const uint8_t kNoState[16];
static const TransientStatsElement kNoRow;

// ------------------------------------------------------------- the seams

static void nothing(EndGameMenusBase *m, BScreenMessage msg,
                    BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

static const char *get_translated_string(int32_t id)
{
    const char *s = gStartRaceTranslateFn != NULL ? gStartRaceTranslateFn(id)
                                                  : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static const char *get_translated_string_by_name(const char *s)
{
    const char *t = gStartRaceTranslateStringFn != NULL
                        ? gStartRaceTranslateStringFn(s) : NULL;

    return t != NULL ? t : s;
}

// CarTypeInfo::GetShortName, 0x00187eb8, as endresults.c's.
static const char *car_type_info_get_short_name(const CarTypeInfo *ct)
{
    return get_translated_string(ct->pCarSpecs->FullName);
}

// DriverInfo::GetName, 0x00188770, as endresults.c's.
static const char *driver_info_get_name(const DriverInfo *d)
{
    if (d->pCharacterInfo == NULL)
        return "";
    return d->pCharacterInfo->CharacterName;
}

// SprintfAndHash, 0x001dc4d0, as endresults.c's.
static uint32_t sprintf_and_hash(const char *fmt, int32_t n)
{
    char buf[32];

    snprintf(buf, sizeof buf, fmt, (int)n);
    return bchunk_hash(buf);
}

static void render_text_into_group(uint32_t screen, uint32_t group,
                                   const char *str)
{
    if (gRenderTextIntoGroupFn != NULL)
        gRenderTextIntoGroupFn(screen, group, str);
}

// RenderTextIntoGroup(int, int, int), 0x00144b58: the string translated.
static void render_id_into_group(uint32_t screen, uint32_t group, int32_t id)
{
    render_text_into_group(screen, group, get_translated_string(id));
}

// GetTheRightTrackLanguageID; a NULL TrackInfo reads zeros in retail.
static int32_t track_language_id(const TrackInfo *t, int32_t dir)
{
    return t != NULL ? get_the_right_track_language_id(t, dir) : 0;
}

// TransientStats::GetDriver; none reads zeros in retail.
static const TransientStatsElement *driver_row(int32_t driver)
{
    const TransientStatsElement *e =
        transient_stats_get_driver(&Fred.TransientStatsTable, driver);

    return e != NULL ? e : &kNoRow;
}

// PlayerTextColors by player number. Retail indexes it unchecked, and 2
// lands on DefaultTextColor; the port is DefaultTextColor for anything
// but 0 and 1.
static const bVector4 *player_color(int32_t n)
{
    return n == 0 || n == 1 ? &PlayerTextColors[n] : &DefaultTextColor;
}

// A place's name. Retail reads the table unchecked; past its 0 the port
// reads 0 too.
static int32_t place_name(int32_t place)
{
    return place >= 0 && place < 10 ? kPlaceNames[place] : 0;
}

// --------------------------------------------------------- the vtables

const EndGameMenusVTable kTourneyStandingsVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    tourney_standings_destroy,
};

const EndGameMenusVTable kEventRewardVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    event_reward_destroy,
};

const EndGameMenusVTable kEventsUnlockedVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    events_unlocked_destroy,
};

const EndGameMenusVTable kBTCResults1PVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    btc_results_1p_destroy,
};

// Its Render is its own (0x001e0bc8), and as empty as the base's.
const EndGameMenusVTable kBTCResults2PVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    btc_results_2p_destroy,
};

void tourney_standings_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kTourneyStandingsVTable;
    endgame_menus_base_destroy(m, flags);
}

void event_reward_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kEventRewardVTable;
    endgame_menus_base_destroy(m, flags);
}

void events_unlocked_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kEventsUnlockedVTable;
    endgame_menus_base_destroy(m, flags);
}

void btc_results_1p_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kBTCResults1PVTable;
    endgame_menus_base_destroy(m, flags);
}

void btc_results_2p_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kBTCResults2PVTable;
    endgame_menus_base_destroy(m, flags);
}

// ------------------------------------------------- the tourney standings

// 0x001dd5c0: the lower rank first. Retail's is a strict <, and bList::Sort
// swaps whatever is not in order, so two cars on one rank swap for ever.
// RacerRank breaks ties by the racer index, so only two cars on one index
// tie; the port's <= keeps them in the list's order and ends.
static int32_t tourney_in_order(bNode *a, bNode *b)
{
    return ((const TourneyPoints *)(void *)a)->Rank
           <= ((const TourneyPoints *)(void *)b)->Rank;
}

typedef struct TourneyRow {
    uint32_t Pos, Name, Type, Race, Total;
} TourneyRow;

static void tourney_row(TourneyRow *r, int32_t n)
{
    r->Pos = sprintf_and_hash("POS_%d", n);
    r->Name = sprintf_and_hash("NAME_%d", n);
    r->Type = sprintf_and_hash("TYPE_%d", n);
    r->Race = sprintf_and_hash("RACE_%d", n);
    r->Total = sprintf_and_hash("TOTAL_%d", n);
}

static void tourney_row_visibility(uint32_t hash, const TourneyRow *r,
                                   int32_t v)
{
    flailer_set_visibility(hash, r->Pos, v);
    flailer_set_visibility(hash, r->Name, v);
    flailer_set_visibility(hash, r->Type, v);
    flailer_set_visibility(hash, r->Race, v);
    flailer_set_visibility(hash, r->Total, v);
}

// The racer index's place in the event's results. Retail reads any
// index; the port's past the eight is 0, no place.
static int32_t event_place(int32_t driver)
{
    int32_t i = raceevent_racer_index_from_driver_number(&TheRaceEvent,
                                                         driver);

    return i >= 0 && i < 8 ? TheRaceEvent.aResults[i].nPosition : 0;
}

// Row k from 0: the car's place in the points, its driver, its car, what
// this race gave it ("DNF" without a place) and its total, in its
// player's colour for a player. The first player's row says the
// tournament speech, once per list: the place after a race, or the end.
// Retail reads through a NULL world car or player for a player's name;
// the port's is "". A car without a driver or a ride, which no racing
// car is, is left shown and unwritten, where retail reads through NULL.
static void show_tourney_row(uint32_t hash, const TourneyPoints *tp,
                             int32_t k)
{
    const struct Car *car = tp->Car->pCar;
    const DriverInfo *d = car->MyDriver;
    const bVector4 *color = &DefaultTextColor;
    const CarTypeInfo *ct;
    const struct Player *p;
    EndGameScreens *s;
    TourneyRow r;
    int32_t place;

    tourney_row(&r, k + 1);
    if (k >= pCurrentRace->NumRacingCars) {
        tourney_row_visibility(hash, &r, FLAILER_OBJECT_INVISIBLE);
        return;
    }
    tourney_row_visibility(hash, &r, FLAILER_OBJECT_VISIBLE);
    if (d == NULL || car->pRideInfo == NULL)
        return;
    ct = cartypeinfo_get(car->pRideInfo->Type);
    place = event_place(d->UniqueDriverNumber);
    if (d->TheDriverType == DRIVER_TYPE_PLAYER) {
        const struct Car *pc =
            world_get_car_by_driver_number(d->UniqueDriverNumber);

        flailer_printf(hash, r.Name, "%s",
                       pc != NULL && pc->pPlayer != NULL
                           ? pc->pPlayer->PlayerSettings.PlayerName : "");
    } else {
        flailer_printf(hash, r.Name, "%s", driver_info_get_name(d));
    }
    flailer_printf(hash, r.Pos, "%2d", (int)(k + 1));
    flailer_printf(hash, r.Type, "%s",
                   get_translated_string_by_name(
                       car_type_info_get_short_name(ct)));
    if (place != 0)
        flailer_printf(hash, r.Race, "%d",
                       (int)tournament_state_points_for_finish_pos(
                           place - 1));
    else
        flailer_printf(hash, r.Race, "DNF");
    flailer_printf(hash, r.Total, "%d", (int)tp->Points);
    p = racingcar_get_player(tp->Car);
    if (p != NULL) {
        color = player_color(p->PlayerNumber);
        s = pEndGameScreens;
        if (s != NULL) {
            if (TOURNEY_SPEECH_SAID(s) == 0) {
                int32_t st = raceevent_get_status(&TheRaceEvent);

                tournament_race_speech(st == EVENT_FAILED
                                       || st == EVENT_PASSED, k);
            }
            TOURNEY_SPEECH_SAID(s) = 1;
        }
    }
    flailer_set_object_color(hash, r.Pos, color);
    flailer_set_object_color(hash, r.Name, color);
    flailer_set_object_color(hash, r.Type, color);
    flailer_set_object_color(hash, r.Race, color);
    flailer_set_object_color(hash, r.Total, color);
}

// Every racing car's points and rank from the tournament's state, in a
// list sorted by rank. Retail reads a NULL state or race as the bottom of
// memory (the port's 16 zeros, and no cars) and any racer index; the
// port's points and rank for an index past the state's 16 bytes are 0. A
// NULL racing car or car is left off the list, where retail reads through
// it.
static void collect_tourney_points(bNode *list)
{
    const RaceEvent *ev = &TheRaceEvent;
    const uint8_t *st = ev->pState != NULL ? ev->pState : kNoState;
    const Race *r = pCurrentRace;
    int32_t n = r == NULL ? 0
                : r->NumRacingCars < RACE_MAX_RACING_CARS
                    ? r->NumRacingCars : RACE_MAX_RACING_CARS;
    int32_t i;

    for (i = 0; i < n; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        TourneyPoints *tp;
        int32_t idx, points = 0, rank = 0;

        if (rc == NULL || rc->pCar == NULL)
            continue;
        idx = raceevent_racer_index_from_driver_number(ev,
                                                       rc->pCar->DriverNumber);
        if (idx >= 0 && idx < (int32_t)sizeof kNoState) {
            points = st[idx];
            rank = tournament_state_racer_rank(st, idx);
        }
        tp = (TourneyPoints *)bMalloc((int)sizeof(TourneyPoints),
                                      "TourneyPoints", 0, END_EVENT_POOL);
        tp->Points = points;
        tp->Rank = rank;
        tp->Node.next = list;
        tp->Node.prev = list->prev;
        list->prev->next = &tp->Node;
        list->prev = &tp->Node;
        tp->Car = rc;
    }
}

EndGameMenusBase *tourney_standings_construct(void *mem, uint32_t hash,
                                              BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    bNode list;
    bNode *node;
    TourneyRow r;
    int32_t k = 0;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kTourneyStandingsVTable;
    set_track_name_and_race_number(m->ScreenHash,
                                   RACE_RESULTS_OBJ_TRACK_NAME,
                                   RACE_RESULTS_OBJ_RACE_NUMBER, 0);
    if (!fred_use_the_race_event(&Fred)
        || TheRaceEvent.nType != EVENT_TOURNAMENT)
        return m;
    list.next = &list;
    list.prev = &list;
    collect_tourney_points(&list);
    blist_sort(&list, tourney_in_order);
    for (node = list.next; node != &list; node = node->next)
        show_tourney_row(m->ScreenHash, (const TourneyPoints *)(void *)node,
                         k++);
    for (; k < TOURNEY_ROWS; k++) {
        tourney_row(&r, k + 1);
        tourney_row_visibility(m->ScreenHash, &r, FLAILER_OBJECT_INVISIBLE);
    }
    while (list.next != &list) {
        node = list.next;
        node->prev->next = node->next;
        node->next->prev = node->prev;
        bFree(node);
    }
    return m;
}

// ---------------------------------------------------- the event's result

int32_t event_reward_user_rank(int32_t driver)
{
    const RaceEvent *ev = &TheRaceEvent;

    if (ev->nType == EVENT_TOURNAMENT) {
        const uint8_t *s = raceevent_get_tournament_state(ev);

        return tournament_state_user_rank(s != NULL ? s : kNoState);
    }
    return driver_row(driver)->FinishPosition;
}

// The tree's blurb for a GameType: the Championship's or the Ultimate
// Racer's, none for another.
static int32_t by_tree(int32_t championship, int32_t ultimate)
{
    if (Fred.GameType == GAME_TYPE_CHAMPIONSHIP)
        return championship;
    if (Fred.GameType == GAME_TYPE_ULTIMATE_RACER)
        return ultimate;
    return 0;
}

int32_t event_reward_lang_id(void)
{
    const RaceEvent *ev = &TheRaceEvent;
    const RaceParameters *rp = &TheRaceParameters;
    int32_t earned = raceevent_any_reward_earned(ev);
    int32_t passed = raceevent_get_status(ev) == EVENT_PASSED;
    uint32_t t = rp->TimeTrialTime.PackedTime;
    int32_t timed = t != 0 && t != NO_TIME;

    if (ev->nNumber == EVENT_TREE_LAST && passed)
        return by_tree(LANG_CHAMPION, LANG_ROAD_RACER);
    if (ev->nNumber == EVENT_ULTIMATE && passed)
        return LANG_HP_CHAMPION;
    if (ev->nNumber == EVENT_TREE_BONUS && passed)
        return by_tree(LANG_BONUS_CHAMPIONSHIP, LANG_BONUS_ULTIMATE);
    if (rp->RaceType == RACE_TYPE_TIME_TRIAL && timed && rp->BeACop == 0) {
        if (!passed)
            return LANG_LAP_FAILED;
        return earned ? LANG_LAP_UNLOCKED : LANG_LAP_PASSED;
    }
    if (rp->Point2Point != 0 && timed && rp->BeACop == 0
        && rp->RaceType != RACE_TYPE_TIME_TRIAL) {
        if (!passed)
            return LANG_TOTAL_FAILED;
        return earned ? LANG_TOTAL_UNLOCKED : LANG_TOTAL_PASSED;
    }
    if (rp->BeACop != 0)
        return passed ? LANG_COP_UNLOCKED : LANG_COP_FAILED;
    if (!passed)
        return LANG_PLACE_FAILED;
    switch (event_reward_user_rank(0)) {
    case 1:
        return earned ? LANG_FIRST_UNLOCKED : LANG_FIRST;
    case 2:
        return earned ? LANG_SECOND_UNLOCKED : LANG_SECOND;
    case 3:
        return earned ? LANG_THIRD_UNLOCKED : LANG_THIRD;
    default:
        return earned ? LANG_PASSED_UNLOCKED : LANG_PASSED;
    }
}

// The texts a blurb can take, all made whatever the blurb: the first
// player's best lap and total time, the time to beat (empty without
// one), the place in the event and the place needed, and the first
// reward's name, read whatever nRewards says. Retail leaves the reward
// unwritten for a reward neither a car nor a track; the port's is empty.
// Retail's buffers are 16 bytes but the reward's 128, and it writes past
// them for a longer text; the port cuts it.
void event_reward_format(char *out, int32_t id)
{
    const RaceEvent *ev = &TheRaceEvent;
    const EventReward *rw = &ev->aRewards[0];
    const char *fmt = get_translated_string(id);
    const TransientStatsElement *row = driver_row(0);
    char best[16], target[16], total[16], place[16], needed[16];
    char reward[128];

    end_game_print_timer(best, row->BestLapTime, 0);
    if (ev->Objective.nType == GOAL_TIME) {
        Timer t;

        t.PackedTime = ev->Objective.nData;
        end_game_print_timer(target, t, 0);
    } else {
        memset(target, 0, sizeof target);
    }
    end_game_print_timer(total, row->RaceTime, 0);
    b_snprintf(place, sizeof place, "%s",
               get_translated_string(place_name(event_reward_user_rank(0))));
    b_snprintf(needed, sizeof needed, "%s",
               get_translated_string(place_name(
                   ev->Objective.nType == GOAL_PLACE
                       ? (int32_t)ev->Objective.nData : 0)));
    reward[0] = 0;
    if (rw->nType == REWARD_CAR) {
        b_snprintf(reward, sizeof reward, "%s",
                   get_translated_string_by_name(
                       car_type_info_get_short_name(
                           cartypeinfo_get(rw->nValue1))));
    } else if (rw->nType == REWARD_TRACK) {
        const char *name = get_translated_string(
            track_language_id(track_get_info(rw->nValue1), rw->nValue2));
        const char *track = get_translated_string(LANG_TRACK);

        b_snprintf(reward, sizeof reward, "%s %s", name, track);
    }
    switch (id) {
    case LANG_LAP_FAILED:
        b_snprintf(out, 256, fmt, best, target);
        break;
    case LANG_LAP_UNLOCKED:
        b_snprintf(out, 256, fmt, best, reward);
        break;
    case LANG_TOTAL_FAILED:
        b_snprintf(out, 256, fmt, total, target);
        break;
    case LANG_TOTAL_UNLOCKED:
        b_snprintf(out, 256, fmt, total, reward);
        break;
    case LANG_COP_UNLOCKED:
    case LANG_FIRST_UNLOCKED:
    case LANG_SECOND_UNLOCKED:
    case LANG_THIRD_UNLOCKED:
    case LANG_PASSED_UNLOCKED:
        b_snprintf(out, 256, fmt, reward);
        break;
    case LANG_LAP_PASSED:
        b_snprintf(out, 256, fmt, best);
        break;
    case LANG_TOTAL_PASSED:
        b_snprintf(out, 256, fmt, total);
        break;
    case LANG_PLACE_FAILED:
        b_snprintf(out, 256, fmt, place, needed);
        break;
    default:
        b_snprintf(out, 256, fmt);
        break;
    }
}

// The speech, once per list: the reward's for a passed event that is not
// the Ultimate nor a bonus event that was not the last one open, the
// event's otherwise.
static void event_reward_speech(int32_t earned)
{
    const RaceEvent *ev = &TheRaceEvent;
    struct Player *p = PlayerPlayersByNumber[0];

    if (raceevent_get_status(ev) != EVENT_PASSED
        || ev->nNumber == EVENT_ULTIMATE
        || (ev->nNumber == EVENT_TREE_BONUS && ev->bIsLastOpen == 0))
        race_event_speech(p, transient_stats_get_driver(
                                 &Fred.TransientStatsTable, 0));
    else
        race_event_reward_speech(p, earned,
                                 ev->nRewards > 0
                                     ? (const uint8_t *)&ev->aRewards[0]
                                     : NULL);
}

// The event's title, its blurb and, for a car the race has just earned,
// the count of cars unlocked. pEndGameScreens is read unchecked in retail;
// with none the port says nothing.
EndGameMenusBase *event_reward_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    RaceEvent *ev = &TheRaceEvent;
    EndGameScreens *s;
    char buf[256];
    int32_t earned;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kEventRewardVTable;
    earned = raceevent_any_reward_earned(ev);
    s = pEndGameScreens;
    if (s != NULL) {
        if (EVENT_REWARD_SPEECH_SAID(s) == 0)
            event_reward_speech(earned);
        EVENT_REWARD_SPEECH_SAID(s) = 1;
    }
    event_reward_format(buf, event_reward_lang_id());
    render_text_into_group(m->ScreenHash, END_REWARD_GROUP_BLURB, buf);
    flailer_printf(m->ScreenHash, END_REWARD_OBJ_TITLE,
                   get_translated_string(
                       raceevent_get_status(ev) == EVENT_PASSED
                           ? END_EVENT_LANG_PASSED : END_EVENT_LANG_FAILED),
                   (int)ev->nNumber);
    if (ev->nRewards > 0 && ev->aRewards[0].nType == REWARD_CAR
        && raceevent_status_advanced(ev)
        && raceevent_reward_earned(ev, 0, NULL))
        end_reward_show_car_count(m->ScreenHash, 0);
    else
        end_reward_clear_car_count(m->ScreenHash);
    return m;
}

// --------------------------------------------------- the events unlocked

// The events this race opened, by number, then the event speech once per
// list. Retail asks GetStatus and drops the answer. Its switch on the
// count has no breaks, so one event prints three times and two twice,
// each over the last with the same blurb; the blurbs read only their
// own. Without a blurb (no event, or four) retail shows the buffer
// unwritten; the port's is empty. pEndGameScreens is read unchecked in
// retail; with none the port says nothing.
EndGameMenusBase *events_unlocked_construct(void *mem, uint32_t hash,
                                            BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    EndGameScreens *s;
    int32_t out[8];
    char buf[256];
    int32_t n, id = 0;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kEventsUnlockedVTable;
    memset(out, 0, sizeof out);
    buf[0] = 0;
    (void)raceevent_get_status(&TheRaceEvent);
    n = events_opened_passed(&TheEventsOpened, out, 8, &TheRaceEvent);
    if (Fred.GameType == GAME_TYPE_CHAMPIONSHIP) {
        if (n > 3)
            n = 3;
        id = n >= 0 ? kChampionshipUnlocked[n] : 0;
    } else if (Fred.GameType == GAME_TYPE_ULTIMATE_RACER) {
        if (n > 3)
            n = 3;
        id = n >= 0 ? kUltimateRacerUnlocked[n] : 0;
    }
    switch (n) {
    case 1:
        b_snprintf(buf, sizeof buf, get_translated_string(id), (int)out[0]);
        // fall through
    case 2:
        b_snprintf(buf, sizeof buf, get_translated_string(id), (int)out[0],
                   (int)out[1]);
        // fall through
    case 3:
        b_snprintf(buf, sizeof buf, get_translated_string(id), (int)out[0],
                   (int)out[1], (int)out[2]);
        break;
    default:
        break;
    }
    render_text_into_group(m->ScreenHash, END_REWARD_GROUP_BLURB, buf);
    flailer_set_language_id(m->ScreenHash, END_REWARD_OBJ_TITLE,
                            END_EVENT_LANG_UNLOCKED);
    s = pEndGameScreens;
    if (s != NULL && EVENTS_UNLOCKED_SPEECH_SAID(s) == 0) {
        race_event_speech(PlayerPlayersByIndex[0],
                          transient_stats_get_driver(
                              &Fred.TransientStatsTable, 0));
        EVENTS_UNLOCKED_SPEECH_SAID(s) = 1;
    }
    end_reward_clear_car_count(m->ScreenHash);
    return m;
}

// ---------------------------------------------------- You're The Cop

static void show_btc_track_name(uint32_t hash)
{
    flailer_set_language_id(hash, RACE_RESULTS_OBJ_TRACK_NAME,
                            track_language_id(
                                CurrentTrackInfo,
                                TheRaceParameters.TrackDirection));
}

// The first player's pursuit: when the cop won, the seconds left (cut to
// a whole number, as cvt.w.s does) and their bonus; the race's points,
// with the bonus, and the career's.
EndGameMenusBase *btc_results_1p_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    const TransientStatsElement *row;
    int32_t bonus = 0;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kBTCResults1PVTable;
    show_btc_track_name(m->ScreenHash);
    row = driver_row(0);
    if (row->FinishReason == BTC_REASON_WON) {
        flailer_set_group_visibility(m->ScreenHash, BTC_GROUP_TIME_BONUS,
                                     FLAILER_OBJECT_VISIBLE);
        flailer_printf(m->ScreenHash, BTC_OBJ_TIME_LEFT, "%d",
                       (int)ee_trunc_w(row->BeACopTime));
        bonus = (int32_t)((uint32_t)ee_trunc_w(row->BeACopTime)
                          * BTC_TIME_BONUS_PER_SECOND);
        flailer_printf(m->ScreenHash, BTC_OBJ_TIME_BONUS, "%d", (int)bonus);
    } else {
        flailer_set_group_visibility(m->ScreenHash, BTC_GROUP_TIME_BONUS,
                                     FLAILER_OBJECT_INVISIBLE);
    }
    flailer_printf(m->ScreenHash, BTC_OBJ_POINTS, "%d",
                   (int)row->PointsThisRace);
    flailer_printf(m->ScreenHash, BTC_OBJ_POINTS_EARNED, "%d",
                   (int)(int32_t)((uint32_t)row->PointsThisRace
                                  + (uint32_t)bonus));
    flailer_printf(m->ScreenHash, BTC_OBJ_POINTS_TOTAL, "%d",
                   (int)row->PointsTotal);
    return m;
}

// Who won the split-screen pursuit, from the two players' finishes: the
// cop's arrest, the speeder's escape, or the time run out on both. Any
// other pair leaves the blurbs as they are. Then each player's points.
EndGameMenusBase *btc_results_2p_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    const TransientStatsElement *a, *b;
    uint32_t h;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kBTCResults2PVTable;
    h = m->ScreenHash;
    show_btc_track_name(h);
    a = driver_row(0);
    b = driver_row(1);
    if (a->FinishReason == BTC_REASON_WON
        && b->FinishReason == BTC_REASON_LOST) {
        render_id_into_group(h, BTC_GROUP_P1_BLURB, LANG_BTC_COP_WON);
        render_id_into_group(h, BTC_GROUP_P2_BLURB, LANG_BTC_SPEEDER_LOST);
    } else if (a->FinishReason == BTC_REASON_LOST) {
        if (b->FinishReason == BTC_REASON_COMPLETED
            || b->FinishReason == BTC_REASON_WON) {
            render_id_into_group(h, BTC_GROUP_P1_BLURB, LANG_BTC_COP_LOST);
            render_id_into_group(h, BTC_GROUP_P2_BLURB,
                                 LANG_BTC_SPEEDER_WON);
        } else if (b->FinishReason == BTC_REASON_LOST) {
            render_id_into_group(h, BTC_GROUP_P1_BLURB,
                                 LANG_BTC_COP_TIME_UP);
            render_id_into_group(h, BTC_GROUP_P2_BLURB,
                                 LANG_BTC_SPEEDER_TIME_UP);
        }
    }
    flailer_printf(h, BTC_OBJ_P1_POINTS, "%d", (int)a->PointsThisRace);
    flailer_printf(h, BTC_OBJ_P2_POINTS, "%d", (int)b->PointsThisRace);
    return m;
}
