// eventtree -- the career's event trees. See eventtree.h; the decode is
// docs/formats/event-tree.md.

#include "eventtree.h"

#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "cartypeinfo.h"
#include "configitems.h"
#include "esolid.h"
#include "fred.h"
#include "raceinit.h"
#include "timer.h"

#define EVENT_TREE_CHUNK 0x80034a00u

bNode gEventTrees = { &gEventTrees, &gEventTrees };
EventTree *gChampionshipTree;
EventTree *gHotPursuitTree;
EventTree *gEventTreeWord16704;
int32_t gUnlockAllEvents;

const char *const gEventTreeRaceTypeTextureNames[6] = {
    "RACEICON", "TIMETRIALICON", "LAPKNOCKOUTICON", "RACEKNOCKOUTICON",
    "TOURNEYICON", "POINT2POINTICON"
};

// gp-16648: a tournament's points for first to eighth.
static const uint8_t kTournamentPoints[8] = { 10, 6, 4, 3, 2, 1, 0, 0 };

// 0x002baed8: GetFinishString's strings by place, 61000 + place for 0 ..
// 8, then a 0 and the next table's first five (62000 ..), and its 0.
static const int32_t kFinishStrings[16] = {
    61000, 61001, 61002, 61003, 61004, 61005, 61006, 61007, 61008, 0,
    62000, 62001, 62002, 62003, 62004, 0
};

// 0x003342f0, GetFinishString's buffer.
static char sFinishString[64];

static uint32_t rd32(const uint8_t *p)
{
    uint32_t v;

    memcpy(&v, p, 4);
    return v;
}

static void wr32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, 4);
}

// bStrICmp, 0x002536a8, as terraintype.c has it: both characters folded,
// sign-extended, before either is tested.
static int32_t to_upper(char c)
{
    int32_t v = (int8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

static int32_t str_icmp(const char *a, const char *b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca == 0 || cb == 0 || ca != cb)
            return ca - cb;
    }
}

static int32_t egg_is_on(int32_t n)
{
    return gEggIsOnFn != NULL && gEggIsOnFn(n) != 0;
}

// ------------------------------------------------------------ the handles

// The trees the events' handles name. Eight at once; the disc has two.
#define EVENT_TREE_HANDLES 8
static EventTree *sTrees[EVENT_TREE_HANDLES];

static uint32_t tree_handle(EventTree *t)
{
    uint32_t i;

    for (i = 0; i < EVENT_TREE_HANDLES; i++)
        if (sTrees[i] == t)
            return i + 1;
    for (i = 0; i < EVENT_TREE_HANDLES; i++) {
        if (sTrees[i] == NULL) {
            sTrees[i] = t;
            return i + 1;
        }
    }
    return 0;
}

static void release_handle(const EventTree *t)
{
    uint32_t i;

    for (i = 0; i < EVENT_TREE_HANDLES; i++)
        if (sTrees[i] == t)
            sTrees[i] = NULL;
}

EventTree *event_info_tree(const EventInfo *e)
{
    uint32_t h = e->TreeHandle;

    return h - 1u < EVENT_TREE_HANDLES ? sTrees[h - 1u] : NULL;
}

uint8_t *event_info_state(const EventInfo *e)
{
    return e->StateOffset != 0 ? (uint8_t *)&Fred + e->StateOffset : NULL;
}

uint8_t *event_tree_ultimate_state(void)
{
    return Fred.pUltimateState != 0
        ? (uint8_t *)&Fred + Fred.pUltimateState : NULL;
}

// The tree's goal nObjective, as retail adds it: NULL only for a tree with
// no goals and an objective of 0.
static const EventGoal *objective_goal(const EventInfo *e)
{
    const EventTree *t = event_info_tree(e);

    return (const EventGoal *)((uintptr_t)t->pGoals
                               + (uintptr_t)(8 * (intptr_t)e->nObjective));
}

// An event's arrays by byte offset: the counts can run past an array into
// the next one, as retail's reads do.
static int32_t event_array(const EventInfo *e, size_t offset, int32_t i)
{
    int16_t v;

    memcpy(&v, (const uint8_t *)e + offset + 2 * (size_t)i, 2);
    return v;
}

// ------------------------------------------------------------- the states

void rank_state_reset(uint8_t *s)
{
    s[0] = 0;
}

void rank_state_unlock(uint8_t *s, const EventGoal *goal)
{
    (void)goal;
    s[0] = 1;
}

int32_t rank_state_get_status(const uint8_t *s, const EventGoal *goal)
{
    if (s[0] == 0)
        return EVENT_UNTRIED;
    return goal->nData < s[0] ? EVENT_FAILED : EVENT_PASSED;
}

void time_state_reset(uint8_t *s)
{
    wr32(s, 0);
}

void time_state_unlock(uint8_t *s, const EventGoal *goal)
{
    (void)goal;
    wr32(s, (uint32_t)(int32_t)4000.5f);
}

int32_t time_state_get_status(const uint8_t *s, const EventGoal *goal)
{
    int32_t t = (int32_t)rd32(s);

    if (t == 0 || t == 0x7fffffff)
        return EVENT_UNTRIED;
    return (int32_t)goal->nData < t ? EVENT_FAILED : EVENT_PASSED;
}

static int32_t nibble(uint32_t w, int32_t i)
{
    return (int32_t)((w >> (4 * i)) & 15u);
}

static uint32_t set_nibble(uint32_t w, int32_t i, int32_t v)
{
    uint32_t shift = 4u * (uint32_t)i;

    return (w & ~(15u << shift)) | (((uint32_t)v & 15u) << shift);
}

void ko_state_reset(uint8_t *s)
{
    wr32(s + 4, 0);
    wr32(s, 0);
}

void ko_state_unlock(uint8_t *s, const EventGoal *goal, int32_t n)
{
    uint32_t w = rd32(s);
    int32_t i;

    (void)goal;
    for (i = 0; i < 8 && i < n; i++) {
        w = set_nibble(w, i, i + 1);
        wr32(s, w);
    }
}

int32_t ko_state_get_race_index(const uint8_t *s)
{
    uint32_t w = rd32(s);
    int32_t n = 0;
    int32_t i;

    for (i = 0; i < 8; i++)
        if (nibble(w, i) != 0)
            n++;
    return n;
}

int32_t ko_state_get_rank(const uint8_t *s, int32_t i)
{
    return (uint32_t)i < 8u ? nibble(rd32(s), i) : 0;
}

void ko_state_set_rank(uint8_t *s, int32_t i, int32_t rank)
{
    if ((uint32_t)i < 8u)
        wr32(s, set_nibble(rd32(s), i, rank));
}

int32_t ko_state_get_status(const uint8_t *s, const EventGoal *goal)
{
    int32_t first;

    if (ko_state_get_race_index(s) == 0)
        return EVENT_UNTRIED;
    first = nibble(rd32(s), 0);
    if (first == 0)
        return EVENT_INPROGRESS;
    return goal->nData < (uint32_t)first ? EVENT_FAILED : EVENT_PASSED;
}

static void set_selected_car(uint8_t *s, int32_t car, int32_t skin,
                             int32_t dash)
{
    int16_t c = (int16_t)car;

    s[11] = (uint8_t)dash;
    memcpy(s + 8, &c, 2);
    s[10] = (uint8_t)skin;
}

static void get_selected_car(const uint8_t *s, int32_t *car, int32_t *skin,
                             int32_t *dash)
{
    int16_t c;

    memcpy(&c, s + 8, 2);
    *car = c;
    *skin = (int8_t)s[10];
    *dash = (int8_t)s[11];
}

void ko_state_set_selected_car(uint8_t *s, int32_t car, int32_t skin,
                               int32_t dash)
{
    set_selected_car(s, car, skin, dash);
}

void ko_state_get_selected_car(const uint8_t *s, int32_t *car,
                               int32_t *skin, int32_t *dash)
{
    get_selected_car(s, car, skin, dash);
}

void ko_state_set_start_position(uint8_t *s, int32_t i, int32_t pos)
{
    if ((uint32_t)i < 8u)
        wr32(s + 4, set_nibble(rd32(s + 4), i, pos));
}

int32_t ko_state_get_start_position(const uint8_t *s, int32_t i)
{
    return (uint32_t)i < 8u ? nibble(rd32(s + 4), i) : 0;
}

uint32_t ko_state_get_seed(const uint8_t *s)
{
    return rd32(s + 12);
}

void ko_state_new_seed(uint8_t *s)
{
    wr32(s + 12, (uint32_t)bRandomI(-1, &bDefaultSeed));
}

void tournament_state_reset(uint8_t *s)
{
    int32_t i;

    for (i = 7; i >= 0; i--)
        s[i] = 0;
}

void tournament_state_unlock(uint8_t *s, const EventGoal *goal,
                             int32_t races)
{
    int32_t i;

    (void)goal;
    for (i = 0; i < 8; i++)
        s[i] = (uint8_t)(races * kTournamentPoints[i]);
}

// The table past its eighth place is other data in retail, zeros in the
// image; nothing reads that far.
int32_t tournament_state_points_for_finish_pos(int32_t pos)
{
    return (uint32_t)pos < 8u ? kTournamentPoints[pos] : 0;
}

// The points every race gives the field, then the points so far over
// them. Retail traps on a negative count of opponents, whose sum is 0;
// the port answers 0.
int32_t tournament_state_get_race_index(const uint8_t *s, int32_t opponents)
{
    int32_t each = 0;
    int32_t sum = 0;
    int32_t i;

    for (i = 0; i <= opponents; i++)
        each += tournament_state_points_for_finish_pos(i);
    for (i = 0; i < 8; i++)
        sum += s[i];
    if (each == 0)
        return 0;
    return sum / each;
}

int32_t tournament_state_racer_rank(const uint8_t *s, int32_t i)
{
    int32_t mine = s[i];
    int32_t rank = 1;
    int32_t j;

    for (j = 0; j < 8; j++) {
        if (j == i)
            continue;
        if (mine < s[j])
            rank++;
        else if (s[j] == mine && j < i)
            rank++;
    }
    return rank;
}

int32_t tournament_state_user_rank(const uint8_t *s)
{
    return tournament_state_racer_rank(s, 0);
}

int32_t tournament_state_get_status(const uint8_t *s, const EventGoal *goal,
                                    int32_t races, int32_t opponents)
{
    int32_t index = tournament_state_get_race_index(s, opponents);

    if (index == 0)
        return EVENT_UNTRIED;
    if (index < races)
        return EVENT_INPROGRESS;
    return goal->nData < (uint32_t)tournament_state_user_rank(s)
        ? EVENT_FAILED : EVENT_PASSED;
}

void tournament_state_set_selected_car(uint8_t *s, int32_t car,
                                       int32_t skin, int32_t dash)
{
    set_selected_car(s, car, skin, dash);
}

void tournament_state_get_selected_car(const uint8_t *s, int32_t *car,
                                       int32_t *skin, int32_t *dash)
{
    get_selected_car(s, car, skin, dash);
}

uint32_t tournament_state_get_seed(const uint8_t *s)
{
    return rd32(s + 12);
}

void tournament_state_new_seed(uint8_t *s)
{
    wr32(s + 12, (uint32_t)bRandomI(-1, &bDefaultSeed));
}

// -------------------------------------------------------------- EventInfo

const uint8_t *event_info_get_car(const EventInfo *e, int32_t i)
{
    if (i < 0 || i >= e->nCars)
        return NULL;
    return event_info_tree(e)->pCars + 4 * event_array(e, 68, i);
}

const EventGoal *event_info_get_goal(const EventInfo *e, int32_t i)
{
    if (i < 0 || i >= e->nGoals)
        return NULL;
    return event_info_tree(e)->pGoals + event_array(e, 124, i);
}

const uint8_t *event_info_get_track(const EventInfo *e, int32_t i)
{
    if (i < 0 || i >= e->nTracks)
        return NULL;
    return event_info_tree(e)->pTracks + 4 * event_array(e, 108, i);
}

const EventReward *event_info_get_reward(const EventInfo *e, int32_t i)
{
    if (i < 0 || i >= e->nRewards)
        return NULL;
    return event_info_tree(e)->pRewards + event_array(e, 140, i);
}

const uint8_t *event_info_get_opponent(const EventInfo *e, int32_t i)
{
    if (i < 0 || i >= e->nOpponents)
        return NULL;
    return event_info_tree(e)->pOpponents + 4 * event_array(e, 156, i);
}

const EventGoal *event_info_get_objective(const EventInfo *e)
{
    return objective_goal(e);
}

uint8_t *event_info_rank_state(const EventInfo *e)
{
    if (e->nType == EVENT_RACE || e->nType == EVENT_LAP_KNOCKOUT)
        return event_info_state(e);
    return NULL;
}

uint8_t *event_info_tournament_state(const EventInfo *e)
{
    return e->nType == EVENT_TOURNAMENT ? event_info_state(e) : NULL;
}

uint8_t *event_info_ko_state(const EventInfo *e)
{
    return e->nType == EVENT_RACE_KNOCKOUT ? event_info_state(e) : NULL;
}

uint8_t *event_info_time_state(const EventInfo *e)
{
    if (e->nType == EVENT_TIME_TRIAL
        || (e->nType >= EVENT_POINT2POINT && e->nType <= EVENT_BE_A_COP))
        return event_info_state(e);
    return NULL;
}

int32_t event_info_reward_earned(const EventInfo *e, int32_t i)
{
    const EventReward *r = event_info_get_reward(e, i);

    if (r == NULL)
        return 0;
    if (event_info_get_status(e, NULL) < EVENT_FAILED)
        return 0;
    switch (e->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        return !(r->nData < (int32_t)event_info_rank_state(e)[0]);
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        return !(r->nData < (int32_t)rd32(event_info_time_state(e)));
    case EVENT_RACE_KNOCKOUT:
        return !(r->nData < ko_state_get_rank(event_info_ko_state(e), 0));
    case EVENT_TOURNAMENT:
        return !((uint32_t)r->nData < (uint32_t)tournament_state_user_rank(
                     event_info_tournament_state(e)));
    default:
        return 0;
    }
}

int32_t event_info_get_state_size(const EventInfo *e)
{
    switch (e->nType) {
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        return 4;
    case EVENT_RACE_KNOCKOUT:
    case EVENT_TOURNAMENT:
        return 16;
    default:
        return 1;
    }
}

// A place's string. Retail indexes its table with any place; the places
// are 1 .. 8, a knockout's at most 15, and past the table the port gives
// "".
static void finish_place(int32_t place)
{
    const char *s = NULL;

    if ((uint32_t)place < 16u && gFredTranslateFn != NULL)
        s = gFredTranslateFn(kFinishStrings[place]);
    if (s == NULL)
        s = "";
    strncpy(sFinishString, s, sizeof sFinishString - 1);
    sFinishString[sizeof sFinishString - 1] = '\0';
}

const char *event_info_get_finish_string(const EventInfo *e)
{
    uint8_t *s;
    Timer t;

    if (event_info_get_status(e, NULL) < EVENT_FAILED) {
        sFinishString[0] = '\0';
        return sFinishString;
    }
    s = event_info_state(e);
    switch (e->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        finish_place(s[0]);
        break;
    case EVENT_RACE_KNOCKOUT:
        finish_place(ko_state_get_rank(s, 0));
        break;
    case EVENT_TOURNAMENT:
        finish_place(tournament_state_user_rank(s));
        break;
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        t.PackedTime = rd32(s);
        timer_print_to_string(&t, sFinishString, 0,
                              gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0);
        break;
    default:
        break;
    }
    return sFinishString;
}

int32_t event_info_is_last_open(const EventInfo *e)
{
    const EventTree *mine = event_info_tree(e);
    int32_t n;

    for (n = 1; n <= 31; n++) {
        EventInfo *hp = event_tree_get_event_number(gHotPursuitTree, n);
        EventInfo *ch = event_tree_get_event_number(gChampionshipTree, n);

        if (hp != NULL && event_info_get_status(hp, NULL) != EVENT_PASSED
            && (n != e->nNumber || mine != gHotPursuitTree))
            return 0;
        if (ch != NULL && event_info_get_status(ch, NULL) != EVENT_PASSED
            && (n != e->nNumber || mine != gChampionshipTree))
            return 0;
    }
    if (event_info_get_status(
            event_tree_get_event_number(gHotPursuitTree, EVENT_ULTIMATE),
            NULL) > EVENT_LOCKED)
        return 0;
    return event_info_get_status(e, NULL) != EVENT_PASSED;
}

int32_t event_info_get_status(const EventInfo *e, const EventGoal *goal)
{
    const EventTree *tree;
    uint8_t *s;
    int32_t egg = 0;
    int32_t status;

    if (gUnlockAllEvents != 0)
        return EVENT_PASSED;
    tree = event_info_tree(e);
    if (e->nNumber == 31) {
        if (tree->nType == EVENT_TREE_CHAMPIONSHIP)
            egg = egg_is_on(6);
        if (tree->nType == EVENT_TREE_HOT_PURSUIT && egg_is_on(7))
            egg = 1;
    }
    if (goal == NULL) {
        if (e->nNumber == EVENT_ULTIMATE) {
            int32_t n;

            for (n = 1; n <= 31; n++) {
                EventInfo *hp = event_tree_get_event_number(gHotPursuitTree, n);
                EventInfo *ch = event_tree_get_event_number(gChampionshipTree,
                                                            n);

                if (hp != NULL
                    && event_info_get_status(hp, NULL) != EVENT_PASSED)
                    return egg != 0;
                if (ch != NULL
                    && event_info_get_status(ch, NULL) != EVENT_PASSED)
                    return egg != 0;
            }
        } else if (e->nGoals > 0) {
            int32_t passed = 0;
            int32_t i;

            for (i = 0; i < e->nGoals; i++)
                passed |= event_goal_passed(event_info_get_goal(e, i),
                                            tree) != 0;
            if (!passed)
                return egg != 0;
        }
        goal = objective_goal(e);
    }
    s = event_info_state(e);
    switch (e->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        status = rank_state_get_status(s, goal);
        break;
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        status = time_state_get_status(s, goal);
        break;
    case EVENT_RACE_KNOCKOUT:
        status = ko_state_get_status(s, goal);
        break;
    case EVENT_TOURNAMENT:
        status = tournament_state_get_status(s, goal, e->nTracks,
                                             e->nOpponents);
        break;
    default:
        status = EVENT_UNTRIED;
        break;
    }
    if (egg)
        return status != 0 ? status : EVENT_UNTRIED;
    return status;
}

int32_t event_info_get_race_index(const EventInfo *e)
{
    uint8_t *s = event_info_state(e);

    if (s == NULL)
        return 0;
    if (e->nType == EVENT_RACE_KNOCKOUT)
        return ko_state_get_race_index(s);
    if (e->nType == EVENT_TOURNAMENT)
        return tournament_state_get_race_index(s, e->nOpponents);
    return 0;
}

int32_t event_info_get_race_count(const EventInfo *e)
{
    if (e->nType == EVENT_RACE_KNOCKOUT)
        return e->nOpponents;
    if (e->nType == EVENT_TOURNAMENT)
        return e->nTracks;
    return 1;
}

void event_info_reset_state(EventInfo *e)
{
    uint8_t *s = event_info_state(e);

    if (s == NULL)
        return;
    switch (e->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        rank_state_reset(s);
        break;
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        time_state_reset(s);
        break;
    case EVENT_RACE_KNOCKOUT:
        ko_state_reset(s);
        break;
    case EVENT_TOURNAMENT:
        tournament_state_reset(s);
        break;
    default:
        break;
    }
}

void event_info_unlock_state(EventInfo *e)
{
    const EventGoal *goal = objective_goal(e);
    uint8_t *s = event_info_state(e);

    if (s == NULL || goal == NULL)
        return;
    switch (e->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        rank_state_unlock(s, goal);
        break;
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        time_state_unlock(s, goal);
        break;
    case EVENT_RACE_KNOCKOUT:
        ko_state_unlock(s, goal, e->nOpponents + 1);
        break;
    case EVENT_TOURNAMENT:
        tournament_state_unlock(s, goal, e->nTracks);
        break;
    default:
        break;
    }
}

int32_t event_info_is_multi_track(const EventInfo *e)
{
    return (uint32_t)(uint8_t)e->nType - 3u < 2u;
}

void event_info_set_selected_car(EventInfo *e, int32_t car, int32_t skin,
                                 int32_t dash)
{
    if (e->nType == EVENT_RACE_KNOCKOUT)
        ko_state_set_selected_car(event_info_state(e), car, skin, dash);
    else if (e->nType == EVENT_TOURNAMENT)
        tournament_state_set_selected_car(event_info_state(e), car, skin,
                                          dash);
}

void event_info_get_selected_car(const EventInfo *e, int32_t *car,
                                 int32_t *skin, int32_t *dash)
{
    if (e->nType == EVENT_RACE_KNOCKOUT)
        ko_state_get_selected_car(event_info_state(e), car, skin, dash);
    else if (e->nType == EVENT_TOURNAMENT)
        tournament_state_get_selected_car(event_info_state(e), car, skin,
                                          dash);
}

int32_t event_goal_passed(const EventGoal *g, const EventTree *tree)
{
    EventInfo *e = event_tree_get_event_number(tree, g->nEvent);

    return e != NULL && event_info_get_status(e, g) == EVENT_PASSED;
}

// -------------------------------------------------------------- EventTree

static void identity(float *m)
{
    int32_t i;

    for (i = 0; i < 16; i++)
        m[i] = (i % 5 == 0) ? 1.0f : 0.0f;
}

void event_tree_construct(EventTree *t, const char *name)
{
    int32_t i;

    // Retail leaves the opponents' table and the words at 116 .. 127 as
    // the heap had them; the port clears the record first.
    memset(t, 0, sizeof *t);
    t->pName = NULL;
    event_tree_set_name(t, name);
    t->pCameraMover = NULL;
    t->nType = 0;
    t->pCars = NULL;
    t->nCars = 0;
    t->pTracks = NULL;
    t->nTracks = 0;
    t->pGoals = NULL;
    t->nGoals = 0;
    t->pRewards = NULL;
    t->nRewards = 0;
    t->pEvents = NULL;
    t->pLeaves = NULL;
    t->nEvents = 0;
    t->nStateSize = 0;
    t->pPolys = NULL;
    t->nPolys = 0;
    t->pLineTexture = NULL;
    t->pCurrentLeaf = NULL;
    t->pCurrentEvent = NULL;
    memset(t->vCenter, 0, sizeof t->vCenter);
    t->bShowLines = 1;
    identity(t->mNumberMatrix);
    identity(t->mClassMatrix);
    memset(t->RaceTypeToTextureTable, 0, sizeof t->RaceTypeToTextureTable);
    for (i = 0; i < 6; i++) {
        uint32_t hash = bchunk_hash(gEventTreeRaceTypeTextureNames[i]);

        t->RaceTypeToTextureTable[i] = gGetTextureInfoFn != NULL
            ? gGetTextureInfoFn(hash, 1, 0) : NULL;
    }
}

// The leaves are BuildTree's, which the port does not build, so pLeaves
// is always NULL here.
void event_tree_destruct(EventTree *t, int32_t flags)
{
    if (t->pName != NULL)
        bFree(t->pName);
    release_handle(t);
    if (flags & 1)
        bFree(t);
}

int32_t event_tree_set_name(EventTree *t, const char *name)
{
    size_t n;

    if (t->pName != NULL)
        bFree(t->pName);
    if (name == NULL) {
        t->pName = NULL;
        return 0;
    }
    n = strlen(name) + 1;
    t->pName = (char *)bMalloc((int)n, "bWare/inc/bWare.hpp", 666, 16);
    memcpy(t->pName, name, n);
    if (str_icmp(name, bVersionE3 ? "Hot Pursuit E3" : "Hot Pursuit") == 0) {
        gHotPursuitTree = t;
        t->nType = EVENT_TREE_HOT_PURSUIT;
        return 1;
    }
    if (str_icmp(name, bVersionE3 ? "Championship E3" : "Championship")
        == 0) {
        gChampionshipTree = t;
        t->nType = EVENT_TREE_CHAMPIONSHIP;
        return 1;
    }
    return 0;
}

// Retail reads a NULL tree's count from the bottom of memory; the port
// finds nothing in it.
EventInfo *event_tree_get_event_number(const EventTree *t, int32_t n)
{
    int32_t i;

    if (t == NULL)
        return NULL;
    for (i = 0; i < t->nEvents; i++)
        if (t->pEvents[i].nNumber == n)
            return &t->pEvents[i];
    return NULL;
}

int32_t event_tree_get_event_index(const EventTree *t, int32_t n)
{
    EventInfo *e = event_tree_get_event_number(t, n);

    return e != NULL ? (int32_t)(e - t->pEvents) : -1;
}

void event_tree_set_events(EventTree *t, void *events, int32_t size)
{
    EventInfo *e = (EventInfo *)events;
    int32_t n = (int32_t)((uint32_t)size / EVENT_INFO_SIZE);
    uint32_t handle = tree_handle(t);
    int32_t i;

    t->pEvents = e;
    t->pCurrentEvent = e;
    t->nEvents = n;
    for (i = 0; i < n; i++)
        e[i].TreeHandle = handle;
}

// The events' offsets are from &Fred, so `state` lies in Fred.
void event_tree_calc_state_pointers(EventTree *t, uint8_t *state,
                                    int32_t size, int32_t align)
{
    uint32_t base = (uint32_t)(state - (uint8_t *)&Fred);
    int32_t i;

    (void)size;
    t->nStateSize = 0;
    for (i = 0; i < t->nEvents; i++) {
        EventInfo *e = &t->pEvents[i];

        if (event_info_get_state_size(e) < align)
            continue;
        if (e->nNumber == EVENT_ULTIMATE && Fred.pUltimateState != 0) {
            e->StateOffset = Fred.pUltimateState;
            continue;
        }
        e->StateOffset = base + (uint32_t)t->nStateSize;
        t->nStateSize = (t->nStateSize + event_info_get_state_size(e) - 1
                         + align) / align * align;
        if (e->nNumber == EVENT_ULTIMATE)
            Fred.pUltimateState = e->StateOffset;
    }
    for (i = 0; i < t->nEvents; i++) {
        EventInfo *e = &t->pEvents[i];

        if (event_info_get_state_size(e) >= align)
            continue;
        if (e->nNumber == EVENT_ULTIMATE && Fred.pUltimateState != 0) {
            e->StateOffset = Fred.pUltimateState;
            continue;
        }
        e->StateOffset = base + (uint32_t)t->nStateSize;
        t->nStateSize += event_info_get_state_size(e);
        if (e->nNumber == EVENT_ULTIMATE)
            Fred.pUltimateState = e->StateOffset;
    }
}

void event_tree_reset_state(EventTree *t)
{
    int32_t i;

    for (i = 0; i < t->nEvents; i++)
        event_info_reset_state(&t->pEvents[i]);
}

void event_tree_unlock_state(EventTree *t)
{
    int32_t i;

    for (i = 0; i < t->nEvents; i++)
        event_info_unlock_state(&t->pEvents[i]);
}

void event_tree_unlock_current_node(EventTree *t)
{
    event_info_unlock_state(t->pCurrentLeaf->pInfo);
}

// The first reward of the events that is the car, or the track in that
// direction, and its event; -1 for none.
static int32_t find_reward(const EventTree *t, int32_t type, int32_t value,
                           int32_t direction, EventInfo **event)
{
    int32_t i, j;

    for (i = 0; i < t->nEvents; i++) {
        EventInfo *e = &t->pEvents[i];

        for (j = 0; j < e->nRewards; j++) {
            const EventReward *r = event_info_get_reward(e, j);

            if (r->nType == type && r->nValue1 == value
                && (type == REWARD_CAR || r->nValue2 == direction)) {
                *event = e;
                return j;
            }
        }
    }
    *event = NULL;
    return -1;
}

int32_t event_tree_is_car_unlocked(const EventTree *t, int32_t car)
{
    EventInfo *e;
    int32_t i = find_reward(t, REWARD_CAR, car, 0, &e);

    return i >= 0 ? event_info_reward_earned(e, i) : 0;
}

int32_t event_tree_car_is_a_reward(const EventTree *t, int32_t car)
{
    EventInfo *e;

    return find_reward(t, REWARD_CAR, car, 0, &e) >= 0;
}

EventInfo *event_tree_find_event_car_is_a_reward_for(const EventTree *t,
                                                     int32_t car)
{
    EventInfo *e;

    find_reward(t, REWARD_CAR, car, 0, &e);
    return e;
}

int32_t event_tree_is_track_unlocked(const EventTree *t, int32_t track,
                                     int32_t direction)
{
    EventInfo *e;
    int32_t i = find_reward(t, REWARD_TRACK, track, direction, &e);

    return i >= 0 ? event_info_reward_earned(e, i) : 1;
}

int32_t event_tree_track_is_a_reward(const EventTree *t, int32_t track,
                                     int32_t direction)
{
    EventInfo *e;

    return find_reward(t, REWARD_TRACK, track, direction, &e) >= 0;
}

EventInfo *event_tree_find_event_track_is_a_reward_for(const EventTree *t,
                                                       int32_t track,
                                                       int32_t direction)
{
    EventInfo *e;

    find_reward(t, REWARD_TRACK, track, direction, &e);
    return e;
}

// --------------------------------------------------------- over the trees

#define FOR_EACH_TREE(t)                                                  \
    for (bNode *n_ = gEventTrees.next;                                    \
         n_ != &gEventTrees && ((t) = (EventTree *)n_, 1);                \
         n_ = n_->next)

int32_t is_car_an_event_reward(int32_t car)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        if (event_tree_car_is_a_reward(t, car))
            return 1;
    return 0;
}

int32_t event_tree_is_car_unlocked_any(int32_t car)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        if (event_tree_is_car_unlocked(t, car))
            return 1;
    return 0;
}

EventInfo *find_event_that_car_is_a_reward_for(int32_t car)
{
    EventTree *t;

    FOR_EACH_TREE(t) {
        EventInfo *e = event_tree_find_event_car_is_a_reward_for(t, car);

        if (e != NULL)
            return e;
    }
    return NULL;
}

EventInfo *find_event_that_track_is_a_reward_for(int32_t track,
                                                 int32_t direction)
{
    EventTree *t;

    FOR_EACH_TREE(t) {
        EventInfo *e =
            event_tree_find_event_track_is_a_reward_for(t, track, direction);

        if (e != NULL)
            return e;
    }
    return NULL;
}

int32_t is_track_an_event_reward(int32_t track, int32_t direction)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        if (event_tree_track_is_a_reward(t, track, direction))
            return 1;
    return 0;
}

int32_t event_tree_is_track_unlocked_any(int32_t track, int32_t direction)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        if (event_tree_track_is_a_reward(t, track, direction))
            return event_tree_is_track_unlocked(t, track, direction) != 0;
    return 1;
}

int32_t event_trees_num_cars_unlocked(void)
{
    int32_t n = 0;
    int32_t car;

    for (car = 0; car < 64; car++)
        if (is_car_an_event_reward(car) && event_tree_is_car_unlocked_any(car))
            n++;
    return n;
}

void lock_events(void)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        event_tree_reset_state(t);
}

void unlock_events(void)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        event_tree_unlock_state(t);
}

int32_t event_trees_both_ultimates_passed(void)
{
    EventInfo *ch = event_tree_get_event_number(gChampionshipTree,
                                                EVENT_ULTIMATE);
    EventInfo *hp = event_tree_get_event_number(gHotPursuitTree,
                                                EVENT_ULTIMATE);
    int32_t status = event_info_get_status(ch, NULL);

    if (status != EVENT_PASSED)
        return 0;
    return event_info_get_status(hp, NULL) == status;
}

// A tree without a name: retail compares with the bottom of memory, a 0
// in the image, so the port's is "".
EventTree *get_event_tree(const char *name)
{
    EventTree *t;

    FOR_EACH_TREE(t)
        if (str_icmp(name, t->pName != NULL ? t->pName : "") == 0)
            return t;
    return NULL;
}

// ------------------------------------------------------- loader, unloader

static void unlink_tree(EventTree *t)
{
    t->Node.prev->next = t->Node.next;
    t->Node.next->prev = t->Node.prev;
}

int loader_event_tree(uint8_t *chunk)
{
    EventTree *t;
    uint8_t *c;

    if (bchunk_u32(chunk) != EVENT_TREE_CHUNK)
        return 0;
    t = (EventTree *)bMalloc((int)sizeof(EventTree),
                             "..\\indep\\src\\eventtree.cpp", 2186, 16);
    event_tree_construct(t, NULL);
    t->Node.prev = gEventTrees.prev;
    gEventTrees.prev->next = &t->Node;
    gEventTrees.prev = &t->Node;
    t->Node.next = &gEventTrees;
    for (c = chunk + 8; c < chunk + 8 + bchunk_u32(chunk + 4);
         c += 8 + bchunk_u32(c + 4)) {
        uint32_t size = bchunk_u32(c + 4);
        uint8_t *data = c + 8;

        if (t == NULL)
            continue;
        switch (bchunk_u32(c)) {
        case 1:
            if (!event_tree_set_name(t, (const char *)data)) {
                unlink_tree(t);
                event_tree_destruct(t, 3);
                t = NULL;
            }
            break;
        case 0x00034a01u:
            t->pCars = data;
            t->nCars = (int32_t)(size >> 2);
            break;
        case 0x00034a02u:
            t->pTracks = data;
            t->nTracks = (int32_t)(size >> 2);
            break;
        case 0x00034a03u:
            t->pGoals = (const EventGoal *)data;
            t->nGoals = (int32_t)(size >> 3);
            break;
        case 0x00034a04u:
            t->pRewards = (const EventReward *)data;
            t->nRewards = (int32_t)(size >> 3);
            break;
        case 0x00034a05u:
            event_tree_set_events(t, data, (int32_t)size);
            if (t->nType == EVENT_TREE_CHAMPIONSHIP)
                event_tree_calc_state_pointers(t, Fred.ChampionshipState,
                                               EVENT_TREE_STATE_SIZE, 4);
            else if (t->nType == EVENT_TREE_HOT_PURSUIT)
                event_tree_calc_state_pointers(t, Fred.HotPursuitState,
                                               EVENT_TREE_STATE_SIZE, 4);
            break;
        case 0x00034a06u:
            t->pOpponents = data;
            t->nOpponents = (int32_t)(size >> 2);
            break;
        default:
            break;
        }
    }
    return 1;
}

int unloader_event_tree(uint8_t *chunk)
{
    if (bchunk_u32(chunk) != EVENT_TREE_CHUNK)
        return 0;
    gEventTreeWord16704 = NULL;
    gChampionshipTree = NULL;
    gHotPursuitTree = NULL;
    while (gEventTrees.next != &gEventTrees) {
        EventTree *t = (EventTree *)gEventTrees.next;

        unlink_tree(t);
        event_tree_destruct(t, 3);
    }
    return 1;
}
